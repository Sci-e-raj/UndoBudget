#include "kernel/types.h"
#include "kernel/fcntl.h"
#include "kernel/group.h"
#include "user/user.h"

// Run only on a fresh boot with the configurations in tests/blockstress.py.
// Groups 2..9 are used here and cannot be reused by other suites on that boot.
static void
check(int ok, char *why)
{
  if (!ok) {
    fprintf(2, "blockstress: FAIL: %s\n", why);
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

static int
create(char *path)
{
  check(!exists(path), "fresh filesystem fixture");
  int fd = open(path, O_CREATE | O_RDWR);
  check(fd >= 0, "create fixture");
  return fd;
}

static void
member(int gid)
{
  check(setgroup(0) == -1 && setgroup(gid) == 0,
        "shell selected the expected workload group");
}

static void
refill(void)
{
  member(2); // max=3, refill=3
  int fd = create("bs2w");
  uint start = (uint)uptime();
  for (int i = 0; i < 3; i++)
    check(write(fd, "abc" + i, 1) == 1, "write after refill");
  close(fd);
  check((uint)uptime() - start >= 100, "two refills required");
  fd = open("bs2w", O_RDONLY);
  char data[3];
  check(fd >= 0 && read(fd, data, sizeof(data)) == sizeof(data) &&
        memcmp(data, "abc", sizeof(data)) == 0, "all writes persisted");
  close(fd);
  printf("blockstress: PASS refill\n");
}

static void
contend(void)
{
  member(3); // max=12, refill=12
  char *paths[] = {"bs3a", "bs3b", "bs3c", "bs3d"};
  for (int i = 0; i < 4; i++)
    close(create(paths[i]));
  uint start = (uint)uptime();
  check(unlink(paths[0]) == 0, "exhaust initial balance");
  for (int i = 1; i < 4; i++) {
    int pid = fork();
    check(pid >= 0, "fork contender");
    if (pid == 0)
      exit(unlink(paths[i]) == 0 && !exists(paths[i]) ? 0 : 2);
  }
  check(pause(150) == 0, "observe competing waiters");
  int survivors = 0;
  for (int i = 1; i < 4; i++)
    survivors += exists(paths[i]);
  check(survivors >= 1, "refilled points were not overspent");
  for (int i = 1; i < 4; i++) {
    int status = -1;
    check(wait(&status) > 0 && status == 0, "contender completed");
  }
  check((uint)uptime() - start >= 200, "three refills required");
  for (int i = 1; i < 4; i++)
    check(!exists(paths[i]), "contender removed its own target");
  printf("blockstress: PASS contend\n");
}

static void
insufficient(void)
{
  member(4); // max=12, refill=3
  close(create("bs4a"));
  close(create("bs4b"));
  uint start = (uint)uptime();
  check(unlink("bs4a") == 0, "exhaust initial balance");
  int pid = fork();
  check(pid >= 0, "fork waiter");
  if (pid == 0)
    exit(unlink("bs4b") == 0 ? 0 : 2);
  check(pause(220) == 0, "observe partial refill");
  check(exists("bs4b"), "insufficient wakeups must not unlink");
  int status = -1;
  check(wait(&status) == pid && status == 0, "waiter eventually completed");
  check((uint)uptime() - start >= 300, "four refills required");
  check(!exists("bs4b"), "admitted unlink completed");
  printf("blockstress: PASS insufficient\n");
}

static void
zero(void)
{
  member(5); // max=12, refill=0
  close(create("bs5a"));
  close(create("bs5b"));
  check(unlink("bs5a") == 0, "exhaust initial balance");
  uint start = (uint)uptime();
  check(unlink("bs5b") == -1, "zero refill refuses instead of waiting");
  check((uint)uptime() - start < 50, "zero-refill refusal was prompt");
  check(exists("bs5b"), "refused target survived");
  printf("blockstress: PASS zero\n");
}

static void
killed_waiter(void)
{
  member(6); // max=12, refill=1
  close(create("bs6a"));
  close(create("bs6b"));
  check(unlink("bs6a") == 0, "exhaust initial balance");
  int ready[2];
  check(pipe(ready) == 0, "ready pipe");
  int pid = fork();
  check(pid >= 0, "fork kill target");
  if (pid == 0) {
    close(ready[0]);
    check(write(ready[1], "r", 1) == 1, "signal readiness");
    close(ready[1]);
    exit(unlink("bs6b") == 0 ? 0 : 2);
  }
  close(ready[1]);
  char token;
  check(read(ready[0], &token, 1) == 1 && token == 'r', "waiter ready");
  close(ready[0]);
  check(pause(20) == 0, "allow waiter to sleep");
  check(exists("bs6b"), "target intact before kill");
  check(kill(pid) == 0, "kill sleeping waiter");
  int status = 0;
  check(wait(&status) == pid && status == -1, "killed waiter exits");
  check(exists("bs6b"), "killed waiter did not unlink");
  printf("blockstress: PASS killed\n");
}

static void
reconfigure(void)
{
  member(7); // shell configured max=12, refill=0, mode=BLOCK once
  check(setbudget(7, 120, 120, BUDGET_BLOCK) == -1,
        "workload cannot reconfigure group");
  close(create("bs7a"));
  close(create("bs7b"));
  check(unlink("bs7a") == 0, "original maximum admitted one unlink");
  check(pause(105) == 0, "pass one refill boundary");
  check(unlink("bs7b") == -1 && exists("bs7b"),
        "rejected shell reconfiguration did not add refill");
  printf("blockstress: PASS reconfigure\n");
}

static void
independent(int gid)
{
  member(gid); // groups 8 and 9: max=3, refill=3
  char *own = gid == 8 ? "bs8w" : "bs9w";
  char *marker = gid == 8 ? "bs8ready" : "bs9ready";
  char *other = gid == 8 ? "bs9ready" : "bs8ready";
  int fd = create(own);
  printf("blockstress: READY independent %d\n", gid);
  close(create(marker));
  int seen = 0;
  for (int i = 0; i < 200; i++) {
    if (exists(other)) {
      seen = 1;
      break;
    }
    check(pause(1) == 0, "wait for other group");
  }
  check(seen, "other group reached barrier");
  uint start = (uint)uptime();
  for (int i = 0; i < 3; i++)
    check(write(fd, "xyz" + i, 1) == 1, "independent group refill");
  close(fd);
  uint elapsed = (uint)uptime() - start;
  check(elapsed >= 100 && elapsed < 350,
        "independent groups each refill their own balance");
  printf("blockstress: PASS independent %d\n", gid);
}

int
main(int argc, char **argv)
{
  check(argc >= 2, "usage: blockstress mode [gid]");
  if (strcmp(argv[1], "refill") == 0 && argc == 2)
    refill();
  else if (strcmp(argv[1], "contend") == 0 && argc == 2)
    contend();
  else if (strcmp(argv[1], "insufficient") == 0 && argc == 2)
    insufficient();
  else if (strcmp(argv[1], "zero") == 0 && argc == 2)
    zero();
  else if (strcmp(argv[1], "killed") == 0 && argc == 2)
    killed_waiter();
  else if (strcmp(argv[1], "reconfigure") == 0 && argc == 2)
    reconfigure();
  else if (strcmp(argv[1], "independent") == 0 && argc == 3 &&
           (strcmp(argv[2], "8") == 0 || strcmp(argv[2], "9") == 0))
    independent(argv[2][0] - '0');
  else
    check(0, "unknown mode or arguments");
  exit(0);
}
