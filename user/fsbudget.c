#include "kernel/types.h"
#include "kernel/fcntl.h"
#include "kernel/group.h"
#include "kernel/stat.h"
#include "user/user.h"

static void
check(int ok, char *why)
{
  if (!ok) {
    fprintf(2, "fsbudget: FAIL: %s\n", why);
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
spent(int gid, uint64 before, int cost)
{
  struct budget_snapshot state;
  check(budgetstat(gid, &state) == 0 && state.remaining + cost == before,
        "exact operation cost");
}

static void
costs(void)
{
  check(setgroup(14) == 0 && setgroup(0) == -1, "run in group 14");
  check(!exists("fbfile") && !exists("fbdir") && !exists("fbdev") &&
          !exists("fblink"),
        "fresh filesystem image");
  struct budget_snapshot state;
  check(budgetstat(14, &state) == 0 && state.remaining == 196 &&
          state.n_allowed == 1,
        "own exec costs 4");
  uint64 balance = state.remaining;

  int fd = open("fbfile", O_CREATE | O_RDWR);
  check(fd >= 0, "create file");
  spent(14, balance, 4);
  balance -= 4;
  check(write(fd, "x", 1) == 1, "seed file content");
  spent(14, balance, 3);
  balance -= 3;
  close(fd);

  fd = open("fbfile", O_CREATE | O_RDWR);
  check(fd >= 0, "O_CREATE on existing file");
  close(fd);
  spent(14, balance, 4);
  balance -= 4;

  fd = open("fbfile", O_TRUNC | O_RDWR);
  check(fd >= 0, "truncate file");
  struct stat st;
  check(fstat(fd, &st) == 0 && st.size == 0, "file was truncated");
  close(fd);
  spent(14, balance, 10);
  balance -= 10;

  fd = open("fbfile", O_CREATE | O_TRUNC | O_RDWR);
  check(fd >= 0, "combined create and truncate");
  close(fd);
  spent(14, balance, 14);
  balance -= 14;

  check(mkdir("fbdir") == 0, "mkdir");
  spent(14, balance, 6);
  balance -= 6;
  check(mknod("fbdev", 1, 0) == 0, "mknod");
  spent(14, balance, 6);
  balance -= 6;
  check(link("fbfile", "fblink") == 0, "link");
  spent(14, balance, 3);
  check(exists("fblink"), "new link exists");
  printf("fsbudget: PASS costs\n");
}

static void
deny(void)
{
  check(setgroup(15) == 0 && setgroup(0) == -1, "run in group 15");
  struct stat before, after;
  check(stat("README", &before) == 0, "read existing file metadata");
  check(!exists("fbnew") && !exists("fbdeny") && !exists("fbnode") &&
          !exists("fbnewlink"),
        "fresh refusal targets");
  check(open((char *)(uint64)-1, O_CREATE | O_RDWR) == -1,
        "invalid user path rejected before charging");
  check(open("fbnew", O_CREATE | O_RDWR) == -1 && !exists("fbnew"),
        "refused creation had no effect");
  check(open("README", O_TRUNC | O_RDWR) == -1 && stat("README", &after) == 0 &&
          after.size == before.size,
        "refused truncation preserved contents");
  check(mkdir("fbdeny") == -1 && !exists("fbdeny"),
        "refused mkdir had no effect");
  check(mknod("fbnode", 1, 0) == -1 && !exists("fbnode"),
        "refused mknod had no effect");
  check(link("README", "fbnewlink") == -1 && !exists("fbnewlink"),
        "refused link had no effect");
  struct budget_snapshot state;
  check(budgetstat(15, &state) == 0 && state.remaining == 2 &&
          state.n_allowed == 1 && state.n_refused == 5,
        "all five charges refused without deduction");
  printf("fsbudget: PASS deny\n");
}

int
main(int argc, char **argv)
{
  check(argc == 2, "usage: fsbudget costs|deny");
  if (strcmp(argv[1], "costs") == 0)
    costs();
  else if (strcmp(argv[1], "deny") == 0)
    deny();
  else
    check(0, "unknown mode");
  exit(0);
}
