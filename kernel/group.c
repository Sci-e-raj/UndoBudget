#include "types.h"
#include "param.h"
#include "riscv.h"
#include "spinlock.h"
#include "proc.h"
#include "defs.h"
#include "group.h"

// All mutable fields are protected by this group's lock. Slots persist for
// the lifetime of the kernel, even when no processes belong to the group.
struct group {
  struct spinlock lock;
  int configured;
  int mode;
  uint64 max;
  uint64 remaining;
  uint64 refill_per_100_ticks;
  uint last_refill;
  uint64 n_allowed;
  uint64 n_blocked;
  uint64 n_refused;
};

static struct group groups[NGROUP];

// Called on the boot CPU before processes or other CPUs start running.
void
groupinit(void)
{
  for (int gid = 0; gid < NGROUP; gid++) {
    struct group *g = &groups[gid];
    initlock(&g->lock, "group");
    g->configured = 0;
    g->mode = BUDGET_FAIL;
    g->max = 0;
    g->remaining = 0;
    g->refill_per_100_ticks = 0;
    g->last_refill = 0;
    g->n_allowed = 0;
    g->n_blocked = 0;
    g->n_refused = 0;
  }
}

int
ksetgroup(int gid)
{
  if (gid < 0 || gid >= NGROUP)
    return -1;

  struct proc *p = myproc();
  if (gid == p->gid)
    return 0;
  if (p->gid != 0)
    return -1;

  // Configuration is permanent once published under the group lock.
  struct group *g = &groups[gid];
  acquire(&g->lock);
  int configured = g->configured;
  release(&g->lock);
  if (!configured)
    return -1;

  // Only the running process changes its own gid; fork copies it before
  // making the child runnable, and exec does not alter it.
  p->gid = gid;
  return 0;
}

// Read a coherent value snapshot under the group lock. Copying to user space
// happens afterwards because copyout may fault in a lazily allocated page.
int
kbudgetstat(int gid, uint64 dst)
{
  struct proc *p = myproc();
  if (p == 0 || gid < 0 || gid >= NGROUP || dst >= p->sz ||
      sizeof(struct budget_snapshot) > p->sz - dst)
    return -1;

  struct budget_snapshot out;
  memset(&out, 0, sizeof(out)); // Includes ABI padding; expose no stack data.
  struct group *g = &groups[gid];
  acquire(&g->lock);
  out.gid = gid;
  out.configured = g->configured;
  out.remaining = g->remaining;
  out.max = g->max;
  out.refill_per_100_ticks = g->refill_per_100_ticks;
  out.mode = g->mode;
  out.n_allowed = g->n_allowed;
  out.n_blocked = g->n_blocked;
  out.n_refused = g->n_refused;
  release(&g->lock);

  return copyout(p->pagetable, p->sz, dst, (char *)&out, sizeof(out));
}

static void
count_event(uint64 *counter)
{
  if (*counter != (uint64)-1)
    (*counter)++;
}

int
ksetbudget(int gid, int max, int refill_per_100_ticks, int mode)
{
  // Check before indexing or converting signed arguments to unsigned fields.
  if (gid < 0 || gid >= NGROUP || max < 0 || refill_per_100_ticks < 0 ||
      (mode != BUDGET_FAIL && mode != BUDGET_BLOCK))
    return -1;
  // Group zero is the trusted administrator. Workloads cannot reset a budget.
  if (myproc()->gid != 0)
    return -1;

  struct group *g = &groups[gid];
  // Lock order is tickslock -> group lock. The configured check and first
  // configuration are atomic under the group lock.
  acquire(&tickslock);
  acquire(&g->lock);
  if (g->configured) {
    release(&g->lock);
    release(&tickslock);
    return -1;
  }
  g->max = max;
  g->remaining = max;
  g->refill_per_100_ticks = refill_per_100_ticks;
  g->mode = mode;
  g->last_refill = ticks;
  g->configured = 1;
  release(&g->lock);
  release(&tickslock);
  return 0;
}

// Called with tickslock and the group lock held. A positive return means a
// BLOCK charge can become affordable after a future refill.
static int
charge_locked(struct group *g, uint64 cost, int deduct)
{
  if (!g->configured || g->remaining > g->max) {
    count_event(&g->n_refused);
    return -1;
  }

  // Unsigned tick subtraction also handles a single 32-bit wrap. Advance by
  // whole periods only so a partial period remains for the next charge.
  uint periods = (ticks - g->last_refill) / 100;
  if (periods > 0) {
    g->last_refill += periods * 100;
    if (g->refill_per_100_ticks > 0 && g->remaining < g->max) {
      uint64 room = g->max - g->remaining;
      uint64 rate = g->refill_per_100_ticks;
      if ((uint64)periods > room / rate)
        g->remaining = g->max;
      else
        g->remaining += (uint64)periods * rate;
    }
  }

  if (cost > g->remaining) {
    if (g->mode == BUDGET_BLOCK && cost <= g->max &&
        g->refill_per_100_ticks > 0)
      return 1;
    count_event(&g->n_refused);
    return -1;
  }
  if (deduct) {
    g->remaining -= cost;
    count_event(&g->n_allowed);
  }
  return 0;
}

// Returns 0 on success, -1 on refusal, or 1 when a non-sleeping caller
// should drop its other locks and wait. deduct=0 only waits for affordability.
static int
charge_current(long cost, int deduct, int may_sleep)
{
  struct proc *p = myproc();
  if (p == 0 || p->gid < 0 || p->gid >= NGROUP || cost < 0)
    return -1;
  if (cost == 0)
    return 0; // Free operations also work before a group is configured.

  struct group *g = &groups[p->gid];
  int waited = 0;
  for (;;) {
    if (waited && killed(p)) {
      acquire(&g->lock);
      count_event(&g->n_refused);
      release(&g->lock);
      return -1;
    }

    // Hold tickslock through the balance check and wait registration. This
    // excludes both timer wakeups and other balance changes in that interval.
    acquire(&tickslock);
    acquire(&g->lock);
    int result = charge_locked(g, (uint64)cost, deduct);
    release(&g->lock);
    if (result != 1 || !may_sleep) {
      release(&tickslock);
      return result;
    }

    // sleep_prepare takes p->lock, but sleep() must run with no locks held.
    if (killed(p)) {
      acquire(&g->lock);
      count_event(&g->n_refused);
      release(&g->lock);
      release(&tickslock);
      return -1;
    }
    acquire(&g->lock);
    count_event(&g->n_blocked);
    release(&g->lock);
    sleep_prepare(&ticks);
    release(&tickslock);
    sleep();
    waited = 1;
  }
}

int
group_charge(long cost)
{
  return charge_current(cost, 1, 1);
}

// For call sites that hold filesystem locks: never sleep or leave a charge
// pending. A return of 1 asks the caller to retry after waiting elsewhere.
int
group_try_charge(long cost)
{
  return charge_current(cost, 1, 0);
}

int
group_wait_affordable(long cost)
{
  return charge_current(cost, 0, 1);
}
