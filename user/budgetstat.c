#include "kernel/types.h"
#include "kernel/param.h"
#include "kernel/fcntl.h"
#include "kernel/group.h"
#include "user/user.h"

// Fresh boot: budget 12 12 0 fail; group 12; budgetstat race
// Then:       budget 13 3 3 block; group 13; budgetstat block
static void
print_text(char *value, int width)
{
  printf("%s", value);
  for (int i = strlen(value); i < width; i++)
    printf(" ");
}

static void
print_number(uint64 value, int width)
{
  int digits = 1;
  for (uint64 n = value; n >= 10; n /= 10)
    digits++;
  for (int i = digits; i < width; i++)
    printf(" ");
  printf("%lu", value);
}

static void
table(void)
{
  print_text("ID", 2);
  printf("  ");
  print_text("CFG", 3);
  printf("  ");
  print_text("MODE", 5);
  printf("  ");
  print_text("REMAINING/MAX", 21);
  printf("  ");
  print_text("REF/100", 10);
  printf("  ");
  print_text("ALLOWED", 8);
  printf("  ");
  print_text("BLOCKED", 8);
  printf("  REFUSED\n");

  for (int gid = 0; gid < NGROUP; gid++) {
    struct budget_snapshot state;
    if (budgetstat(gid, &state) < 0) {
      fprintf(2, "budgetstat: snapshot of group %d failed\n", gid);
      exit(1);
    }
    char *mode = state.mode == BUDGET_FAIL ? "FAIL" :
                 state.mode == BUDGET_BLOCK ? "BLOCK" : "?";
    print_number(state.gid, 2);
    printf("  ");
    print_text(state.configured ? "yes" : "no", 3);
    printf("  ");
    print_text(state.configured ? mode : "-", 5);
    printf("  ");
    print_number(state.remaining, 10);
    printf("/");
    print_number(state.max, 10);
    printf("  ");
    print_number(state.refill_per_100_ticks, 10);
    printf("  ");
    print_number(state.n_allowed, 8);
    printf("  ");
    print_number(state.n_blocked, 8);
    printf("  ");
    print_number(state.n_refused, 8);
    printf("\n");
  }
  printf("Balances are stored snapshots; lazy refill occurs on charge.\n");
  printf("ALLOWED=charges; BLOCKED=wait registrations; REFUSED=charge refusals.\n");
}

static void
check(int ok, char *why)
{
  if (!ok) {
    fprintf(2, "budgetstat: FAIL: %s\n", why);
    exit(1);
  }
}

static int
create(char *path)
{
  check(open(path, O_RDONLY) < 0, "fresh filesystem fixture");
  int fd = open(path, O_CREATE | O_RDWR);
  check(fd >= 0, "create fixture");
  return fd;
}

static void
race(void)
{
  check(setgroup(0) == -1 && setgroup(12) == 0, "selected group 12");
  struct budget_snapshot before, now;
  check(budgetstat(12, &before) == 0, "initial snapshot");
  check(before.gid == 12 && before.configured == 1 && before.max == 12 &&
        before.remaining == 12 && before.refill_per_100_ticks == 0 &&
        before.mode == BUDGET_FAIL && before.n_allowed == 0 &&
        before.n_blocked == 0 && before.n_refused == 0,
        "initial configured values and zero counters");

  now = before;
  check(budgetstat(-1, &now) == -1 && budgetstat(NGROUP, &now) == -1 &&
        memcmp(&before, &now, sizeof(now)) == 0,
        "invalid gids do not copy out");
  check(budgetstat(12, 0) == -1 &&
        budgetstat(12, (struct budget_snapshot *)(uint64)-1) == -1 &&
        budgetstat(12, (struct budget_snapshot *)(uint64)race) == -1,
        "invalid and read-only user buffers rejected");
  char *end = sbrk(0);
  check(end != SBRK_ERROR &&
        budgetstat(12, (struct budget_snapshot *)(end - 1)) == -1,
        "buffer extending past process size rejected");
  check(budgetstat(12, &now) == 0 &&
        memcmp(&before, &now, sizeof(now)) == 0,
        "invalid requests did not mutate group state");
  check(budgetstat(14, &now) == 0 && now.gid == 14 && !now.configured &&
        now.remaining == 0 && now.max == 0 && now.n_allowed == 0 &&
        now.n_blocked == 0 && now.n_refused == 0,
        "unconfigured group has safe zero snapshot");

  char *paths[] = {"stat0", "stat1", "stat2", "stat3", "stat4", "stat5"};
  for (int i = 0; i < 6; i++)
    close(create(paths[i]));
  int ready[2], start[2];
  check(pipe(ready) == 0 && pipe(start) == 0, "barrier pipes");
  for (int i = 0; i < 6; i++) {
    int pid = fork();
    check(pid >= 0, "fork writer");
    if (pid == 0) {
      close(ready[0]);
      close(start[1]);
      int fd = open(paths[i], O_WRONLY);
      if (fd < 0 || write(ready[1], "r", 1) != 1)
        exit(2);
      char token;
      if (read(start[0], &token, 1) != 1)
        exit(2);
      int result = write(fd, "x", 1);
      close(fd);
      exit(result == 1 ? 0 : result == -1 ? 1 : 2);
    }
  }
  close(ready[1]);
  close(start[0]);
  for (int i = 0; i < 6; i++) {
    char token;
    check(read(ready[0], &token, 1) == 1 && token == 'r',
          "all writers ready");
  }
  close(ready[0]);
  check(write(start[1], "xxxxxx", 6) == 6, "release writers");
  close(start[1]);

  for (int i = 0; i < 50; i++) {
    check(budgetstat(12, &now) == 0, "concurrent snapshot");
    check(now.gid == 12 && now.configured == 1 && now.max == 12 &&
          now.refill_per_100_ticks == 0 && now.mode == BUDGET_FAIL &&
          now.remaining <= now.max && now.n_allowed <= 4 &&
          now.n_refused <= 6 && now.n_blocked == 0 &&
          now.remaining + 3 * now.n_allowed == 12,
          "each snapshot is coherent during racing deductions");
    if (i % 10 == 0)
      check(pause(1) == 0, "yield to writers");
  }

  int allowed = 0, refused = 0;
  for (int i = 0; i < 6; i++) {
    int status = -1;
    check(wait(&status) > 0 && (status == 0 || status == 1),
          "writer completed");
    allowed += status == 0;
    refused += status == 1;
  }
  check(allowed == 4 && refused == 2, "only four writes admitted");
  check(budgetstat(12, &now) == 0 && now.remaining == 0 &&
        now.n_allowed == 4 && now.n_blocked == 0 && now.n_refused == 2,
        "final counters count charge outcomes once");
  int written = 0;
  for (int i = 0; i < 6; i++) {
    int fd = open(paths[i], O_RDONLY);
    check(fd >= 0, "read writer fixture");
    char byte;
    int n = read(fd, &byte, 1);
    check(n == 0 || (n == 1 && byte == 'x'), "file content valid");
    written += n == 1;
    close(fd);
  }
  check(written == allowed, "refused writes left files unchanged");
  printf("budgetstat: PASS race\n");
}

static void
block(void)
{
  check(setgroup(0) == -1 && setgroup(13) == 0, "selected group 13");
  int fd = create("statb");
  check(write(fd, "a", 1) == 1, "first charge");
  struct budget_snapshot now, later;
  check(budgetstat(13, &now) == 0 && now.gid == 13 &&
        now.configured == 1 && now.max == 3 && now.remaining == 0 &&
        now.refill_per_100_ticks == 3 && now.mode == BUDGET_BLOCK &&
        now.n_allowed == 1 && now.n_blocked == 0 && now.n_refused == 0,
        "first charge snapshot");
  check(write(fd, "b", 1) == 1, "blocked charge eventually admitted");
  check(budgetstat(13, &now) == 0 && now.n_allowed == 2 &&
        now.n_blocked >= 1 && now.n_refused == 0 && now.remaining == 0,
        "wait episodes counted; admission counted once");
  check(pause(105) == 0, "pass refill boundary");
  check(budgetstat(13, &later) == 0 && later.remaining == now.remaining &&
        later.n_allowed == now.n_allowed &&
        later.n_blocked == now.n_blocked &&
        later.n_refused == now.n_refused,
        "snapshot does not apply lazy refill or alter counters");
  close(fd);
  printf("budgetstat: PASS block\n");
}

int
main(int argc, char **argv)
{
  if (argc == 1)
    table();
  else if (argc == 2 && strcmp(argv[1], "race") == 0)
    race();
  else if (argc == 2 && strcmp(argv[1], "block") == 0)
    block();
  else {
    fprintf(2, "usage: budgetstat [race|block]\n");
    exit(1);
  }
  exit(0);
}
