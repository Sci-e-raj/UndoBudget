// Direct test of the kernel-only charge API. Build from the repository root:
// gcc -std=gnu99 -fno-builtin -pthread -I. kernel/group.c tests/group_charge_host.c -o /tmp/group_charge_host
#include <limits.h>
#include <pthread.h>
#include <stdio.h>
#include "kernel/types.h"
#include "kernel/param.h"
#include "kernel/riscv.h"
#include "kernel/spinlock.h"
#include "kernel/proc.h"
#include "kernel/defs.h"
#include "kernel/group.h"

struct spinlock tickslock;
uint ticks;
static struct proc test_proc;

struct proc *myproc(void) { return &test_proc; }
void initlock(struct spinlock *lk, char *name) { lk->locked = 0; lk->name = name; }
void acquire(struct spinlock *lk) { while (__sync_lock_test_and_set(&lk->locked, 1)) {} }
void release(struct spinlock *lk) { __sync_lock_release(&lk->locked); }

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL: %s\n", #x); return 1; } } while (0)

static int concurrent_successes;

static void *
charge_worker(void *unused)
{
  (void)unused;
  if (group_charge(1) == 0)
    __sync_fetch_and_add(&concurrent_successes, 1);
  return 0;
}

int
main(void)
{
  groupinit();
  test_proc.gid = -1;
  CHECK(group_charge(0) == -1);
  test_proc.gid = NGROUP;
  CHECK(group_charge(12) == -1);
  test_proc.gid = 0;
  CHECK(group_charge(0) == 0);
  CHECK(group_charge(12) == -1); // Unconfigured positive charge.
  CHECK(ksetbudget(2, 12, 0, BUDGET_FAIL) == 0);
  test_proc.gid = 2;
  CHECK(group_charge(-1) == -1);
  CHECK(group_charge(LONG_MIN) == -1);
  CHECK(group_charge(LONG_MAX) == -1);
  CHECK(group_charge(12) == 0); // Rejections did not spend the balance.
  CHECK(group_charge(1) == -1);
  ticks = 200;
  CHECK(group_charge(1) == -1); // Zero refill never grows the balance.

  test_proc.gid = 0;
  ticks = 17;
  CHECK(ksetbudget(3, 10, 3, BUDGET_FAIL) == 0);
  test_proc.gid = 3;
  CHECK(group_charge(10) == 0);
  ticks = 116;
  CHECK(group_charge(1) == -1); // 99 ticks: no refill.
  test_proc.gid = 0;
  CHECK(ksetbudget(3, 10, 3, BUDGET_FAIL) == -1); // Cannot reset clock.
  test_proc.gid = 3;
  ticks = 166;
  CHECK(group_charge(3) == 0); // 149 ticks: one refill, 49 carried.
  ticks = 216;
  CHECK(group_charge(1) == -1); // 99 ticks since last full boundary.
  ticks = 217;
  CHECK(group_charge(3) == 0); // Exactly 100 ticks since boundary.

  test_proc.gid = 0;
  ticks = 0;
  CHECK(ksetbudget(4, 10, 4, BUDGET_FAIL) == 0);
  test_proc.gid = 4;
  CHECK(group_charge(10) == 0);
  ticks = 250;
  CHECK(group_charge(8) == 0); // Two full periods, 50 ticks carried.
  ticks = 299;
  CHECK(group_charge(1) == -1);
  ticks = 300;
  CHECK(group_charge(4) == 0);

  test_proc.gid = 0;
  ticks = 0;
  CHECK(ksetbudget(5, 7, INT_MAX, BUDGET_FAIL) == 0);
  test_proc.gid = 5;
  CHECK(group_charge(7) == 0);
  ticks = UINT_MAX;
  CHECK(group_charge(7) == 0); // Huge catch-up saturates without overflow.
  ticks = 3;
  CHECK(group_charge(1) == -1); // 99 ticks after last full boundary.
  ticks = 4;
  CHECK(group_charge(7) == 0); // Wrap and one full period.

  test_proc.gid = 0;
  ticks = 0;
  CHECK(ksetbudget(6, INT_MAX, INT_MAX, BUDGET_FAIL) == 0);
  test_proc.gid = 6;
  CHECK(group_charge(INT_MAX) == 0);
  ticks = 99;
  CHECK(group_charge(1) == -1);
  ticks = 100;
  CHECK(group_charge(INT_MAX) == 0); // High max and refill values.

  test_proc.gid = 0;
  ticks = UINT_MAX - 50;
  CHECK(ksetbudget(7, 5, 2, BUDGET_FAIL) == 0);
  test_proc.gid = 7;
  CHECK(group_charge(5) == 0);
  ticks = 48;
  CHECK(group_charge(1) == -1); // 99 ticks spanning wrap.
  ticks = 49;
  CHECK(group_charge(2) == 0); // 100 ticks spanning wrap.

  test_proc.gid = 0;
  ticks = 0;
  CHECK(ksetbudget(8, 100, 10, BUDGET_FAIL) == 0);
  test_proc.gid = 8;
  CHECK(group_charge(100) == 0);
  ticks = 100;
  pthread_t workers[32];
  for (int i = 0; i < 32; i++)
    CHECK(pthread_create(&workers[i], 0, charge_worker, 0) == 0);
  for (int i = 0; i < 32; i++)
    CHECK(pthread_join(workers[i], 0) == 0);
  CHECK(concurrent_successes == 10);
  CHECK(group_charge(1) == -1);

  puts("group_charge_host: PASS (boundaries, cap, wrap, concurrent refill)");
  return 0;
}
