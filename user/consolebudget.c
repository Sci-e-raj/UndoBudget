#include "kernel/types.h"
#include "kernel/fcntl.h"
#include "kernel/group.h"
#include "user/user.h"

static char message[129];

int
main(int argc, char **argv)
{
  if (argc != 2 || (strcmp(argv[1], "128") != 0 && strcmp(argv[1], "129") != 0))
    exit(1);
  int length = atoi(argv[1]);
  int gid = length == 128 ? 15 : 14;
  int fd = open("console", O_WRONLY);
  struct budget_snapshot before, after;
  if (fd < 0 || budgetstat(gid, &before) < 0 ||
      before.remaining != (length == 128 ? 3 : 4) ||
      write(fd, message, 0) != 0 || write(-1, message, 1) != -1 ||
      budgetstat(gid, &after) < 0 || after.remaining != before.remaining ||
      after.n_allowed != before.n_allowed ||
      after.n_refused != before.n_refused)
    exit(1);
  for (int i = 0; i < length; i++)
    message[i] = 'C';
  if (write(fd, message, length) != length || write(fd, "Z", 1) != -1 ||
      budgetstat(gid, &after) < 0 || after.remaining != 0 ||
      after.n_allowed != before.n_allowed + 1 ||
      after.n_refused != before.n_refused + 1)
    exit(1);
  close(fd);
  printf("consolebudget: PASS %d\n", length);
  exit(0);
}
