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
  }
}

int
ksetgroup(int gid)
{
  if (gid < 0 || gid >= NGROUP)
    return -1;
  myproc()->gid = gid;
  return 0;
}

int
ksetbudget(int gid, int max, int refill_per_100_ticks, int mode)
{
  // Check before indexing or converting signed arguments to unsigned fields.
  if (gid < 0 || gid >= NGROUP || max < 0 || refill_per_100_ticks < 0 ||
      (mode != BUDGET_FAIL && mode != BUDGET_BLOCK))
    return -1;
  // Teaching policy: only current members may configure this shared group.
  if (myproc()->gid != gid)
    return -1;

  struct group *g = &groups[gid];
  // Lock order is tickslock -> group lock. Keep the timestamp and reset atomic.
  acquire(&tickslock);
  acquire(&g->lock);
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
