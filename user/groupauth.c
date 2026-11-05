#include "kernel/types.h"
#include "kernel/param.h"
#include "kernel/group.h"
#include "user/user.h"

#define INT_MAX 2147483647
#define INT_MIN (-INT_MAX - 1)
#define TEST_GROUP (NGROUP - 3)
#define RACE_GROUP (NGROUP - 2)
#define RACERS 4

static void
check(int ok, char *message)
{
  if (!ok) {
    fprintf(2, "groupauth: FAIL: %s\n", message);
    exit(1);
  }
}

static void
check_workload(void)
{
  check(setgroup(0) == -1, "cannot return to administrator group");
  check(setgroup(TEST_GROUP) == 0, "same-group call");
  check(setgroup(RACE_GROUP) == -1, "cannot switch workload groups");
  check(setbudget(TEST_GROUP, 1, 0, BUDGET_FAIL) == -1,
        "workload cannot reset its budget");
  check(setbudget(0, 1, 0, BUDGET_FAIL) == -1,
        "workload cannot configure administrator group");
  check(setbudget(NGROUP - 1, 1, 0, BUDGET_FAIL) == -1,
        "workload cannot configure another group");
}

int
main(int argc, char **argv)
{
  if (argc == 2 && strcmp(argv[1], "after-exec") == 0) {
    check_workload();
    exit(0);
  }

  check(setgroup(-1) == -1 && setgroup(NGROUP) == -1 &&
        setgroup(INT_MIN) == -1 && setgroup(INT_MAX) == -1,
        "invalid group IDs");
  check(setgroup(0) == 0, "same administrator group");
  check(setgroup(TEST_GROUP) == -1, "unconfigured group rejected");
  check(setbudget(-1, 1, 0, BUDGET_FAIL) == -1 &&
        setbudget(NGROUP, 1, 0, BUDGET_FAIL) == -1 &&
        setbudget(INT_MIN, 1, 0, BUDGET_FAIL) == -1 &&
        setbudget(INT_MAX, 1, 0, BUDGET_FAIL) == -1,
        "invalid budget group IDs");
  check(setbudget(TEST_GROUP, -1, 0, BUDGET_FAIL) == -1 &&
        setbudget(TEST_GROUP, INT_MIN, 0, BUDGET_FAIL) == -1,
        "negative maximum");
  check(setbudget(TEST_GROUP, 1, -1, BUDGET_FAIL) == -1 &&
        setbudget(TEST_GROUP, 1, INT_MIN, BUDGET_FAIL) == -1,
        "negative refill");
  check(setbudget(TEST_GROUP, 1, 0, -1) == -1 &&
        setbudget(TEST_GROUP, 1, 0, BUDGET_BLOCK + 1) == -1 &&
        setbudget(TEST_GROUP, 1, 0, INT_MAX) == -1,
        "invalid mode");

  check(setbudget(0, 100, 10, BUDGET_FAIL) == -1,
        "init configured administrator group");
  check(setbudget(0, 1, 0, BUDGET_FAIL) == -1,
        "administrator group cannot be reset");
  check(setbudget(1, 100, 10, BUDGET_FAIL) == -1,
        "init configured default workload group");

  int bootstrap = fork();
  check(bootstrap >= 0, "default workload fork");
  if (bootstrap == 0) {
    check(setgroup(1) == 0, "enter configured default group");
    check(setgroup(0) == -1, "default group cannot return to administrator");
    check(setbudget(1, 1, 0, BUDGET_FAIL) == -1,
          "default workload cannot configure its group");
    exit(0);
  }
  int bootstrap_status = -1;
  check(wait(&bootstrap_status) == bootstrap && bootstrap_status == 0,
        "default workload exits");

  check(setbudget(TEST_GROUP, INT_MAX, INT_MAX, BUDGET_BLOCK) == 0,
        "administrator configures group");
  check(setbudget(TEST_GROUP, 1, 0, BUDGET_FAIL) == -1,
        "duplicate configuration rejected");

  int start[2], results[2];
  check(pipe(start) == 0 && pipe(results) == 0, "race pipes");
  for (int i = 0; i < RACERS; i++) {
    int pid = fork();
    check(pid >= 0, "race fork");
    if (pid == 0) {
      close(start[1]);
      close(results[0]);
      char token;
      check(read(start[0], &token, 1) == 1, "race start");
      char result = setbudget(RACE_GROUP, 20, 1, BUDGET_FAIL) == 0 ? '1' : '0';
      check(write(results[1], &result, 1) == 1, "race result");
      exit(0);
    }
  }
  close(start[0]);
  close(results[1]);
  check(write(start[1], "xxxx", RACERS) == RACERS, "release racers");
  close(start[1]);
  int successes = 0;
  for (int i = 0; i < RACERS; i++) {
    char result;
    check(read(results[0], &result, 1) == 1, "collect race result");
    check(result == '0' || result == '1', "valid race result");
    successes += result == '1';
  }
  close(results[0]);
  check(successes == 1, "exactly one configuration succeeds");
  for (int i = 0; i < RACERS; i++) {
    int status = -1;
    check(wait(&status) > 0 && status == 0, "race child exits");
  }

  int pid = fork();
  check(pid >= 0, "workload fork");
  if (pid == 0) {
    check(setgroup(TEST_GROUP) == 0, "enter configured group");
    check_workload();
    int child = fork();
    check(child >= 0, "inherited workload fork");
    if (child == 0) {
      check_workload();
      exit(0);
    }
    int status = -1;
    check(wait(&status) == child && status == 0, "fork inheritance");
    char *args[] = {"groupauth", "after-exec", 0};
    exec("groupauth", args);
    check(0, "exec self");
  }
  int status = -1;
  check(wait(&status) == pid && status == 0, "workload and exec");
  printf("groupauth: PASS\n");
  exit(0);
}
