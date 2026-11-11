#include "kernel/types.h"
#include "kernel/group.h"
#include "user/user.h"

static void
check(int ok, char *why)
{
  if (!ok) {
    fprintf(2, "execbudget: FAIL %s\n", why);
    exit(1);
  }
}

int
main(int argc, char **argv)
{
  check(argc == 2, "usage");
  char *hello[] = {"hello", 0};
  struct budget_snapshot before, after;

  if (strcmp(argv[1], "deny") == 0) {
    check(setgroup(15) == 0 && setgroup(0) == -1, "selected group 15");
    check(budgetstat(15, &before) == 0 && before.remaining == 3 &&
            before.n_allowed == 1,
          "own launch cost 4");
    check(exec("hello", hello) == -1, "insufficient budget refused exec");
    check(budgetstat(15, &after) == 0 && after.remaining == 3 &&
            after.n_allowed == before.n_allowed &&
            after.n_refused == before.n_refused + 1,
          "refusal preserved image and balance");
    check(write(1, "execbudget: PASS deny\n", 22) == 22, "report result");
    exit(0);
  }
  check(strcmp(argv[1], "allow") == 0, "mode");
  check(setgroup(14) == 0 && setgroup(0) == -1, "selected group 14");
  check(budgetstat(14, &before) == 0 && before.remaining == 196 &&
          before.n_allowed == 1,
        "own launch cost 4");
  char *bad[] = {"README", 0};
  check(exec("README", bad) == -1, "invalid ELF rejected");
  check(budgetstat(14, &after) == 0 && after.remaining == before.remaining &&
          after.n_allowed == before.n_allowed &&
          after.n_refused == before.n_refused,
        "invalid ELF was not charged");
  exec("hello", hello);
  check(0, "valid exec did not replace image");
  exit(1);
}
