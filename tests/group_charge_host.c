// Direct test of the kernel-only charge API. Build from the repository root:
// gcc -std=gnu99 -fno-builtin -I. kernel/group.c tests/group_charge_host.c -o /tmp/group_charge_host
#include <limits.h>
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
  puts("group_charge_host: PASS");
  return 0;
}
