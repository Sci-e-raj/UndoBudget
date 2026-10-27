#include "kernel/types.h"
#include "kernel/param.h"
#include "kernel/group.h"
#include "user/user.h"

#define INT_MAX 2147483647
#define INT_MIN (-INT_MAX - 1)
#define TEST_GROUP (NGROUP - 1)

static void
check(int ok, char *message)
{
  if (!ok) {
    fprintf(2, "grouptest: FAIL: %s\n", message);
    exit(1);
  }
}

static void
check_member(void)
{
  // Do not call setgroup here: success must come from inherited membership.
  check(setbudget(TEST_GROUP, 100, 10, BUDGET_FAIL) == 0,
        "inherited membership");
  check(setbudget(0, 100, 10, BUDGET_FAIL) == -1,
        "cannot configure another group");
}

int
main(int argc, char **argv)
{
  if (argc == 2 && strcmp(argv[1], "exec-child") == 0) {
    check_member();
    exit(0);
  }

  check(setgroup(0) == 0, "join group zero");
  check(setbudget(TEST_GROUP, 100, 10, BUDGET_FAIL) == -1,
        "nonmember configuration rejected");
  check(setgroup(TEST_GROUP) == 0, "join last valid group");

  int badids[] = {-1, NGROUP, INT_MIN, INT_MAX};
  for (int i = 0; i < sizeof(badids) / sizeof(badids[0]); i++) {
    check(setgroup(badids[i]) == -1, "invalid group rejected");
    check(setbudget(badids[i], 100, 10, BUDGET_FAIL) == -1,
          "invalid budget group rejected");
    check_member(); // A rejected setgroup must leave membership unchanged.
  }
  check(setbudget(TEST_GROUP, -1, 0, BUDGET_FAIL) == -1, "negative max");
  check(setbudget(TEST_GROUP, INT_MIN, 0, BUDGET_FAIL) == -1, "minimum max");
  check(setbudget(TEST_GROUP, 1, -1, BUDGET_FAIL) == -1, "negative refill");
  check(setbudget(TEST_GROUP, 1, INT_MIN, BUDGET_FAIL) == -1, "minimum refill");
  check(setbudget(TEST_GROUP, 1, 0, -1) == -1, "negative mode");
  check(setbudget(TEST_GROUP, 1, 0, BUDGET_BLOCK + 1) == -1, "unknown mode");
  check(setbudget(TEST_GROUP, 1, 0, INT_MAX) == -1, "large mode");
  check(setbudget(TEST_GROUP, 0, 0, BUDGET_FAIL) == 0, "zero budget");
  check(setbudget(TEST_GROUP, 1, INT_MAX, BUDGET_BLOCK) == 0,
        "refill larger than max");
  check(setbudget(TEST_GROUP, INT_MAX, INT_MAX, BUDGET_BLOCK) == 0,
        "maximum signed arguments");
  check_member();

  // Make the parent switch groups before the child checks its inherited gid.
  int gate[2];
  check(pipe(gate) == 0, "pipe");
  int pid = fork();
  check(pid >= 0, "fork");
  if (pid == 0) {
    close(gate[1]);
    char token;
    check(read(gate[0], &token, 1) == 1, "parent signal");
    close(gate[0]);
    check_member();
    check(exec("/no-such-file", argv) == -1, "failed exec");
    check_member();
    char *args[] = {"grouptest", "exec-child", 0};
    exec("grouptest", args);
    check(0, "exec self");
  }
  close(gate[0]);
  check(setgroup(0) == 0, "parent changes group");
  check(write(gate[1], "x", 1) == 1, "release child");
  close(gate[1]);
  int status = -1;
  check(wait(&status) == pid && status == 0, "fork and exec inheritance");
  check(setbudget(TEST_GROUP, 100, 10, BUDGET_FAIL) == -1,
        "child did not change parent membership");

  // Reuse process slots and contend on one shared group from several CPUs.
  check(setgroup(TEST_GROUP) == 0, "rejoin group");
  for (int i = 0; i < 4; i++) {
    pid = fork();
    check(pid >= 0, "concurrent fork");
    if (pid == 0) {
      for (int j = 0; j < 100; j++)
        check(setbudget(TEST_GROUP, j, j + 1, j % 2) == 0,
              "concurrent configuration");
      exit(0);
    }
  }
  for (int i = 0; i < 4; i++) {
    status = -1;
    check(wait(&status) > 0 && status == 0, "concurrent child exit");
  }
  check_member();
  check(setgroup(0) == 0, "leave test group");
  printf("grouptest: PASS (validation, fork, exec, concurrent configuration)\n");
  exit(0);
}
