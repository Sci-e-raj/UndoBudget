#include "kernel/types.h"
#include "kernel/fcntl.h"
#include "user/user.h"

// On a fresh boot, run: budget 12 12 12 block; group 12; blockrefill
static void
check(int ok, char *message)
{
  if (!ok) {
    fprintf(2, "blockrefill: FAIL: %s\n", message);
    exit(1);
  }
}

int
main(void)
{
  check(setgroup(0) == -1 && setgroup(12) == 0, "selected group 12");

  check(open("br12w", O_RDONLY) < 0 && open("br12d", O_RDONLY) < 0,
        "fresh filesystem fixture");
  int fd = open("br12w", O_CREATE | O_RDWR);
  check(fd >= 0, "create write fixture");
  int target = open("br12d", O_CREATE | O_RDWR);
  check(target >= 0, "create deletion fixture");
  close(target);

  uint start = (uint)uptime();
  for (int i = 0; i < 5; i++)
    check(write(fd, "abcde" + i, 1) == 1, "BLOCK write eventually succeeds");
  close(fd);
  check(unlink("br12d") == 0, "BLOCK unlink eventually succeeds");
  uint elapsed = (uint)uptime() - start;
  // Five 3-unit writes and one 12-unit unlink need two refill periods.
  check(elapsed >= 100, "insufficient balance waited for tick refill");

  fd = open("br12w", O_RDONLY);
  check(fd >= 0, "written file remains");
  char contents[5];
  check(read(fd, contents, sizeof(contents)) == sizeof(contents) &&
        memcmp(contents, "abcde", sizeof(contents)) == 0,
        "writes preserved their contents");
  close(fd);
  check(open("br12d", O_RDONLY) < 0, "unlinked file is absent");
  printf("blockrefill: PASS (%d ticks)\n", elapsed);
  exit(0);
}
