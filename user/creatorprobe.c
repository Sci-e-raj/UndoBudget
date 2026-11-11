#include "kernel/types.h"
#include "kernel/stat.h"
#include "kernel/fcntl.h"
#include "user/user.h"

static void
check(int ok, char *message)
{
  if (!ok) {
    fprintf(2, "creatorprobe: FAIL: %s\n", message);
    exit(1);
  }
}

static void
create(char *path)
{
  struct stat st;
  check(stat(path, &st) == -1, "fixture must not exist");
  int fd = open(path, O_CREATE | O_RDWR);
  check(fd >= 0, "create file");
  close(fd);
}

int
main(int argc, char **argv)
{
  struct stat old, fresh;
  check(argc == 2, "usage: creatorprobe create|replace");
  check(setgroup(0) == -1, "run in workload group");

  if (strcmp(argv[1], "create") == 0) {
    check(setgroup(2) == 0, "select creator group 2");
    create("cg_old");
    check(stat("cg_old", &old) == 0, "stat created file");
    printf("creatorprobe: PASS create inum %d\n", old.ino);
  } else if (strcmp(argv[1], "replace") == 0) {
    check(setgroup(3) == 0, "select creator group 3");
    check(stat("cg_old", &old) == 0, "old file survived reboot");
    check(unlink("cg_old") == 0, "delete old inode");
    create("cg_new");
    check(stat("cg_new", &fresh) == 0, "stat replacement");
    check(fresh.ino == old.ino, "reused the freed disk inode");
    check(stat("cg_old", &old) == -1, "old name removed");
    printf("creatorprobe: PASS replace inum %d\n", fresh.ino);
  } else {
    check(0, "unknown mode");
  }
  exit(0);
}
