#include "kernel/types.h"
#include "kernel/param.h"
#include "kernel/fcntl.h"
#include "user/user.h"

// Run on a fresh boot after: budget 11 12 0 fail; group 11
#define TEST_GID (NGROUP - 5)

static void
check(int ok, char *message)
{
  if (!ok) {
    fprintf(2, "unlinkbudget: FAIL: %s\n", message);
    exit(1);
  }
}

static void
create_file(char *path)
{
  int fd = open(path, O_CREATE | O_RDWR);
  check(fd >= 0, "create file");
  check(close(fd) == 0, "close file");
}

int
main(void)
{
  check(setgroup(0) == -1 && setgroup(TEST_GID) == 0,
        "run in reserved workload group");

  create_file("ub_ok");
  create_file("ub_keep");
  check(mkdir("ub_dir") == 0, "create directory");
  create_file("ub_dir/child");

  // Neither failure should consume the only 12 units.
  check(unlink("ub_missing") == -1, "missing target rejected");
  check(unlink("ub_dir") == -1, "nonempty directory rejected");
  check(unlink("ub_ok") == 0, "permitted unlink");
  check(open("ub_ok", O_RDONLY) == -1, "permitted target removed");

  check(unlink("ub_keep") == -1, "insufficient budget rejected");
  int fd = open("ub_keep", O_RDONLY);
  check(fd >= 0, "refused target survived");
  close(fd);
  printf("unlinkbudget: PASS\n");
  exit(0);
}
