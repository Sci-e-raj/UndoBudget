#include "kernel/types.h"
#include "kernel/fcntl.h"
#include "user/user.h"

// On a fresh boot, configure gid 8/9/10 with 7/15/16 units, no refill.
// Run same, cross-deny, cross-allow in that order, selecting each group.
#define WRITE_LEN 4097

static char data[WRITE_LEN];
static char observed[WRITE_LEN];

static void
check(int ok, char *message)
{
  if (!ok) {
    fprintf(2, "writebudget: FAIL: %s\n", message);
    exit(1);
  }
}

static void
check_contents(char expected)
{
  int fd = open("wbfile", O_RDONLY);
  check(fd >= 0, "open file for verification");
  check(read(fd, observed, WRITE_LEN) == WRITE_LEN, "file length unchanged");
  for (int i = 0; i < WRITE_LEN; i++)
    check(observed[i] == expected, "file contents unchanged");
  char extra;
  check(read(fd, &extra, 1) == 0, "no unexpected extra data");
  close(fd);
}

int
main(int argc, char **argv)
{
  check(argc == 2, "usage: writebudget same|cross-deny|cross-allow");
  check(setgroup(0) == -1, "run in workload group");

  if (strcmp(argv[1], "same") == 0) {
    check(setgroup(8) == 0, "select creator group 8");
    int fd = open("wbfile", O_CREATE | O_RDWR);
    check(fd >= 0, "create test file");
    memset(data, 'A', WRITE_LEN);
    check(write(-1, data, WRITE_LEN) == -1 &&
          write(99, data, WRITE_LEN) == -1 &&
          write(fd, data, -1) == -1,
          "invalid fd and size rejected without charge");
    check(write(fd, data, WRITE_LEN) == WRITE_LEN,
          "same-group 4097-byte write costs 7 once");
    check(write(fd, "X", 1) == -1, "exhausted budget refuses next write");
    check(write(fd, data, 0) == 0, "zero-length write is free");
    close(fd);
    check_contents('A');
  } else if (strcmp(argv[1], "cross-deny") == 0) {
    check(setgroup(9) == 0, "select cross-group 9");
    int fd = open("wbfile", O_WRONLY);
    check(fd >= 0, "open file owned by group 8");
    memset(data, 'B', WRITE_LEN);
    check(write(fd, data, WRITE_LEN) == -1,
          "15 units cannot pay cross-group cost 16");
    close(fd);
    check_contents('A');
  } else if (strcmp(argv[1], "cross-allow") == 0) {
    check(setgroup(10) == 0, "select cross-group 10");
    int fd = open("wbfile", O_WRONLY);
    check(fd >= 0, "open file owned by group 8");
    memset(data, 'B', WRITE_LEN);
    check(write(fd, data, WRITE_LEN) == WRITE_LEN,
          "cross-group 4097-byte write costs 16 once");
    close(fd);
    check_contents('B');
  } else {
    check(0, "unknown mode");
  }
  printf("writebudget: PASS %s\n", argv[1]);
  exit(0);
}
