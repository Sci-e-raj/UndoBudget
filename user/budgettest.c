#include "kernel/types.h"
#include "kernel/param.h"
#include "kernel/fcntl.h"
#include "kernel/group.h"
#include "user/user.h"

// Groups 2..7 are reserved for this suite. Configure them from the shell.
#define GID_FIFTY 2
#define GID_SHARED 3
#define GID_FIRST 4
#define GID_SECOND 5
#define GID_RACE 6
#define GID_BOUNDARY 7
#define RACERS 4

static void
check(int ok, char *message)
{
  if (!ok) {
    fprintf(2, "budgettest: FAIL: %s\n", message);
    exit(1);
  }
}

static int
exists(char *path)
{
  int fd = open(path, O_RDONLY);
  if (fd < 0)
    return 0;
  close(fd);
  return 1;
}

static void
create(char *path)
{
  check(!exists(path), "test needs a fresh filesystem image");
  int fd = open(path, O_CREATE | O_RDWR);
  check(fd >= 0, "create fixture");
  close(fd);
}

static void
member(int gid)
{
  check(setgroup(0) == -1 && setgroup(gid) == 0,
        "shell selected the expected workload group");
}

static void
fifty(void)
{
  member(GID_FIFTY);
  char *files[] = {"b50a", "b50b", "b50c", "b50d", "b50e", "b50f"};
  for (int i = 0; i < 6; i++)
    create(files[i]);
  for (int i = 0; i < 4; i++) {
    check(unlink(files[i]) == 0, "one of four 12-unit unlinks");
    check(!exists(files[i]), "permitted unlink removed its target");
  }
  for (int i = 4; i < 6; i++) {
    check(unlink(files[i]) == -1, "budget exhausted after 48 units");
    check(exists(files[i]), "refused target survived");
  }
}

static void
shared(void)
{
  member(GID_SHARED);
  create("bsp");
  create("bsc");
  int pid = fork();
  check(pid >= 0, "fork");
  if (pid == 0) {
    member(GID_SHARED);
    check(unlink("bsc") == 0, "child spends shared budget");
    exit(0);
  }
  int status = -1;
  check(wait(&status) == pid && status == 0, "child completed unlink");
  check(!exists("bsc"), "child target removed");
  check(unlink("bsp") == -1, "parent sees child's deduction");
  check(exists("bsp"), "parent's refused target survived");
}

static void
independent(int gid, char *first, char *second)
{
  member(gid);
  create(first);
  create(second);
  check(unlink(first) == 0, "independent group has 12 units");
  check(!exists(first), "independent group's target removed");
  check(unlink(second) == -1, "independent group exhausted");
  check(exists(second), "independent group's refused target survived");
}

static void
race(void)
{
  member(GID_RACE);
  char *files[] = {"bra", "brb", "brc", "brd"};
  int ready[2], start[2];
  for (int i = 0; i < RACERS; i++)
    create(files[i]);
  check(pipe(ready) == 0 && pipe(start) == 0, "race pipes");
  for (int i = 0; i < RACERS; i++) {
    int pid = fork();
    check(pid >= 0, "race fork");
    if (pid == 0) {
      char token;
      close(ready[0]);
      close(start[1]);
      if (write(ready[1], "x", 1) != 1 || read(start[0], &token, 1) != 1)
        exit(2);
      close(ready[1]);
      close(start[0]);
      int removed = unlink(files[i]) == 0;
      if (exists(files[i]) == removed)
        exit(2);
      exit(removed ? 0 : 1);
    }
  }
  close(ready[1]);
  close(start[0]);
  for (int i = 0; i < RACERS; i++) {
    char token;
    check(read(ready[0], &token, 1) == 1, "all racers ready");
  }
  close(ready[0]);
  check(write(start[1], "xxxx", RACERS) == RACERS, "release racers");
  close(start[1]);

  int successes = 0, survivors = 0;
  for (int i = 0; i < RACERS; i++) {
    int status = -1;
    check(wait(&status) > 0 && (status == 0 || status == 1),
          "race child completed");
    if (status == 0)
      successes++;
  }
  for (int i = 0; i < RACERS; i++) {
    if (exists(files[i]))
      survivors++;
  }
  check(successes == 1 && survivors == RACERS - 1,
        "exactly one charge and deletion admitted");
}

static void
boundary(void)
{
  member(GID_BOUNDARY);
  check(setgroup(-1) == -1 && setgroup(NGROUP) == -1,
        "invalid group IDs rejected");
  check(setbudget(-1, 12, 0, BUDGET_FAIL) == -1 &&
        setbudget(NGROUP, 12, 0, BUDGET_FAIL) == -1,
        "invalid configuration group IDs rejected");
  check(setbudget(GID_BOUNDARY, -1, 0, BUDGET_FAIL) == -1 &&
        setbudget(GID_BOUNDARY, 12, -1, BUDGET_FAIL) == -1 &&
        setbudget(GID_BOUNDARY, 12, 0, -1) == -1,
        "invalid configuration values rejected");
  create("bbound");
  check(unlink("bbound") == -1, "11 units cannot pay 12-unit cost");
  check(exists("bbound"), "underfunded target survived");
}

int
main(int argc, char **argv)
{
  check(argc == 2, "usage: budgettest fifty|shared|first|second|race|boundary");
  if (strcmp(argv[1], "fifty") == 0)
    fifty();
  else if (strcmp(argv[1], "shared") == 0)
    shared();
  else if (strcmp(argv[1], "first") == 0)
    independent(GID_FIRST, "bfa", "bfb");
  else if (strcmp(argv[1], "second") == 0)
    independent(GID_SECOND, "bsa", "bsb");
  else if (strcmp(argv[1], "race") == 0)
    race();
  else if (strcmp(argv[1], "boundary") == 0)
    boundary();
  else
    check(0, "unknown test mode");
  printf("budgettest: PASS %s\n", argv[1]);
  exit(0);
}
