#include "kernel/types.h"
#include "kernel/param.h"
#include "kernel/group.h"
#include "user/user.h"

#define INT_MAX 2147483647
#define INT_MIN (-INT_MAX - 1)
#define TEST_GROUP (NGROUP - 1) // Reserved for this test; configure from sh.

static void
check(int ok, char *message)
{
  if (!ok) {
    fprintf(2, "grouptest: FAIL: %s\n", message);
    exit(1);
  }
}

static void
check_member(int gid)
{
  int other = gid == 1 ? TEST_GROUP : 1;
  // Check group zero first: an accidental reset to zero must not be hidden
  // by a later setgroup(gid) call.
  check(setgroup(0) == -1, "cannot return to administrator group");
  check(setgroup(gid) == 0, "current group preserved");
  check(setgroup(other) == -1, "cannot switch workload groups");
  check(setbudget(gid, 100, 10, BUDGET_FAIL) == -1,
        "cannot reset own group");
  check(setbudget(other, 100, 10, BUDGET_FAIL) == -1,
        "cannot configure another workload group");
  check(setbudget(0, 100, 10, BUDGET_FAIL) == -1,
        "cannot configure administrator group");
}

int
main(int argc, char **argv)
{
  int gid = 1;
  int exec_child = 0;
  if (argc == 2 && strcmp(argv[1], "test") == 0)
    gid = TEST_GROUP;
  else if (argc == 2 && strcmp(argv[1], "exec-default") == 0)
    exec_child = 1;
  else if (argc == 2 && strcmp(argv[1], "exec-test") == 0) {
    gid = TEST_GROUP;
    exec_child = 1;
  } else
    check(argc == 1, "usage: grouptest [test]");

  if (exec_child) {
    check_member(gid);
    exit(0);
  }

  check_member(gid);

  int badids[] = {-1, NGROUP, INT_MIN, INT_MAX};
  for (int i = 0; i < sizeof(badids) / sizeof(badids[0]); i++) {
    check(setgroup(badids[i]) == -1, "invalid group rejected");
    check(setbudget(badids[i], 100, 10, BUDGET_FAIL) == -1,
          "invalid budget group rejected");
    check_member(gid);
  }
  check(setbudget(gid, -1, 0, BUDGET_FAIL) == -1, "negative max");
  check(setbudget(gid, INT_MIN, 0, BUDGET_FAIL) == -1, "minimum max");
  check(setbudget(gid, 1, -1, BUDGET_FAIL) == -1, "negative refill");
  check(setbudget(gid, 1, INT_MIN, BUDGET_FAIL) == -1, "minimum refill");
  check(setbudget(gid, 1, 0, -1) == -1, "negative mode");
  check(setbudget(gid, 1, 0, BUDGET_BLOCK + 1) == -1, "unknown mode");
  check(setbudget(gid, 1, 0, INT_MAX) == -1, "large mode");
  check_member(gid);

  // The parent cannot change groups while the child waits to inspect its
  // inherited gid. Both successful and failed exec must preserve membership.
  int gate[2];
  check(pipe(gate) == 0, "pipe");
  int pid = fork();
  check(pid >= 0, "fork");
  if (pid == 0) {
    close(gate[1]);
    char token;
    check(read(gate[0], &token, 1) == 1, "parent signal");
    close(gate[0]);
    check_member(gid);
    check(exec("/no-such-file", argv) == -1, "failed exec");
    check_member(gid);
    char *args[] = {"grouptest", gid == 1 ? "exec-default" : "exec-test", 0};
    exec("grouptest", args);
    check(0, "exec self");
  }
  close(gate[0]);
  check(setgroup(gid == 1 ? TEST_GROUP : 1) == -1,
        "parent cannot change groups");
  check(write(gate[1], "x", 1) == 1, "release child");
  close(gate[1]);
  int status = -1;
  check(wait(&status) == pid && status == 0, "fork and exec inheritance");
  check_member(gid);

  // Several descendants must all be denied attempts to reset the group.
  for (int i = 0; i < 4; i++) {
    pid = fork();
    check(pid >= 0, "concurrent fork");
    if (pid == 0) {
      for (int j = 0; j < 100; j++)
        check(setbudget(gid, j, j + 1, j % 2) == -1,
              "concurrent reset denied");
      check_member(gid);
      exit(0);
    }
  }
  for (int i = 0; i < 4; i++) {
    status = -1;
    check(wait(&status) > 0 && status == 0, "concurrent child exit");
  }
  check_member(gid);
  printf("grouptest: PASS (group %d)\n", gid);
  exit(0);
}
