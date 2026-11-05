#ifndef XV6_GROUP_H
#define XV6_GROUP_H

// Public mode values for setbudget().
#define BUDGET_FAIL  0
#define BUDGET_BLOCK 1

// Value-only ABI for budgetstat(gid, out). Any process may query a valid gid.
// Include types.h before this header.
// remaining is stored lazy-refill state: budgetstat does not advance it.
// Counters saturate at UINT64_MAX and cover positive-cost kernel charges only:
// n_allowed: successful deductions, one per admitted charge (even if later
//            filesystem work fails); zero-cost operations do not count.
// n_blocked: wait registrations, possibly several per BLOCK charge call.
// n_refused: terminal charge refusals (including killed waiters), not invalid
//            syscall arguments rejected before charging. These are charge
//            events, not necessarily distinct syscalls.
struct budget_snapshot {
  int gid;
  int configured;
  uint64 remaining;
  uint64 max;
  uint64 refill_per_100_ticks;
  int mode;
  uint64 n_allowed;
  uint64 n_blocked;
  uint64 n_refused;
};

#endif
