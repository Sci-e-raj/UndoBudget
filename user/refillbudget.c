#include "kernel/types.h"
#include "kernel/fcntl.h"
#include "user/user.h"

// Run after: budget 8 24 12 fail; group 8
static void
check(int ok, char *message)
{
  if (!ok) {
    fprintf(2, "refillbudget: FAIL: %s\n", message);
    exit(1);
  }
}

static void
create(char *path)
{
  int fd = open(path, O_CREATE | O_RDWR);
  check(fd >= 0, "create fixture");
  close(fd);
}

int
main(void)
{
  check(setgroup(0) == -1 && setgroup(8) == 0, "selected group 8");
  create("rf_a");
  create("rf_b");
  check(unlink("rf_a") == 0, "spend initial 12 units");

  uint start = (uint)uptime();
  check(pause(105) == 0, "wait for refill");
  uint elapsed = (uint)uptime() - start;
  check(elapsed >= 105, "at least one full period elapsed");

  check(unlink("rf_b") == 0, "lazy refill funds second unlink");
  check(open("rf_a", O_RDONLY) == -1 && open("rf_b", O_RDONLY) == -1,
        "both targets removed");
  printf("refillbudget: PASS (elapsed %d ticks)\n", elapsed);
  exit(0);
}
