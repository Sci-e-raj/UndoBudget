#include "kernel/types.h"
#include "kernel/param.h"
#include "kernel/fs.h"
#include "kernel/stat.h"
#include "kernel/fcntl.h"
#include "kernel/group.h"
#include "user/user.h"

// One operation per invocation: agentop ID TOOL PATH_OR_GID
// Records: UB1|ID|ITEM|hex-name, UB1|ID|DATA|hex-bytes, or
// UB1|ID|STAT|nine decimal snapshot fields, then exactly one
// UB1|ID|END|OK or UB1|ID|END|ERR|code. No file data is printed raw.
#define MAX_READ_BYTES 4096
#define MAX_LIST_ENTRIES 256
#define HEX_CHUNK 256

static char file_data[MAX_READ_BYTES + 1];
static char hex_data[2 * HEX_CHUNK];
static char status_data[192];
static char *request_id;

static int
write_all(char *data, int n)
{
  while (n > 0) {
    int written = write(1, data, n);
    if (written <= 0)
      return -1;
    data += written;
    n -= written;
  }
  return 0;
}

static int
emit(char *text)
{
  return write_all(text, strlen(text));
}

static int
prefix(char *kind)
{
  return emit("UB1|") == 0 && emit(request_id) == 0 && emit("|") == 0 &&
         emit(kind) == 0 && emit("|") == 0 ? 0 : -1;
}

static int
end_ok(void)
{
  if (prefix("END") < 0 || emit("OK\n") < 0)
    return -1;
  return 0;
}

static int
end_error(char *code)
{
  if (prefix("END") < 0 || emit("ERR|") < 0 || emit(code) < 0 ||
      emit("\n") < 0)
    return -1;
  return -1;
}

static int
emit_hex(char *kind, char *data, int n)
{
  static char digits[] = "0123456789abcdef";
  if (prefix(kind) < 0)
    return -1;
  for (int i = 0; i < n; i++) {
    uchar byte = (uchar)data[i];
    hex_data[2 * i] = digits[byte >> 4];
    hex_data[2 * i + 1] = digits[byte & 15];
  }
  if (write_all(hex_data, 2 * n) < 0 || emit("\n") < 0)
    return -1;
  return 0;
}

static int
id_ok(char *id)
{
  int n = strlen(id);
  if (n < 1 || n > 64)
    return 0;
  for (int i = 0; i < n; i++) {
    char c = id[i];
    if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
          (c >= '0' && c <= '9') || c == '_' || c == '-'))
      return 0;
  }
  return 1;
}

static int
path_ok(char *path, int allow_dot)
{
  int n = strlen(path);
  if (allow_dot && n == 1 && path[0] == '.')
    return 1;
  if (n < 1 || n >= MAXPATH || path[0] == '/')
    return 0;

  int start = 0;
  for (int i = 0; i <= n; i++) {
    if (path[i] == '/' || path[i] == 0) {
      int length = i - start;
      if (length < 1 || length > DIRSIZ ||
          (length == 1 && path[start] == '.') ||
          (length == 2 && path[start] == '.' && path[start + 1] == '.'))
        return 0;
      start = i + 1;
    } else {
      char c = path[i];
      if (i == start) {
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
              (c >= '0' && c <= '9') || c == '_'))
          return 0;
      } else if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                   (c >= '0' && c <= '9') || c == '_' || c == '.' ||
                   c == '-')) {
        return 0;
      }
    }
  }
  return 1;
}

static int
list_files(char *path)
{
  int fd = open(path, O_RDONLY);
  if (fd < 0)
    return end_error("open_failed");
  struct stat st;
  if (fstat(fd, &st) < 0 || st.type != T_DIR) {
    close(fd);
    return end_error("not_directory");
  }

  struct dirent entry;
  int count = 0, n;
  while ((n = read(fd, &entry, sizeof(entry))) == sizeof(entry)) {
    if (entry.inum == 0)
      continue;
    int length = 0;
    while (length < DIRSIZ && entry.name[length] != 0)
      length++;
    if ((length == 1 && entry.name[0] == '.') ||
        (length == 2 && entry.name[0] == '.' && entry.name[1] == '.'))
      continue;
    if (++count > MAX_LIST_ENTRIES) {
      close(fd);
      return end_error("too_many_entries");
    }
    if (emit_hex("ITEM", entry.name, length) < 0) {
      close(fd);
      return -1;
    }
  }
  close(fd);
  if (n != 0)
    return end_error("read_failed");
  return end_ok();
}

static int
read_file(char *path)
{
  int fd = open(path, O_RDONLY);
  if (fd < 0)
    return end_error("open_failed");
  struct stat st;
  if (fstat(fd, &st) < 0 || st.type != T_FILE) {
    close(fd);
    return end_error("not_file");
  }
  int total = 0;
  for (;;) {
    int n = read(fd, file_data + total, sizeof(file_data) - total);
    if (n < 0) {
      close(fd);
      return end_error("read_failed");
    }
    if (n == 0)
      break;
    total += n;
    if (total > MAX_READ_BYTES) {
      close(fd);
      return end_error("too_large");
    }
  }
  close(fd);
  for (int offset = 0; offset < total; offset += HEX_CHUNK) {
    int n = total - offset;
    if (n > HEX_CHUNK)
      n = HEX_CHUNK;
    if (emit_hex("DATA", file_data + offset, n) < 0)
      return -1;
  }
  return end_ok();
}

static int
delete_file(char *path)
{
  int fd = open(path, O_RDONLY);
  if (fd < 0)
    return end_error("open_failed");
  struct stat st;
  if (fstat(fd, &st) < 0 || st.type != T_FILE) {
    close(fd);
    return end_error("not_file");
  }
  close(fd);

  // xv6 returns -1 for both budget denial and ordinary unlink failures.
  // A preflight check cannot exclude a concurrent rename/deletion race.
  if (unlink(path) < 0)
    return end_error("unlink_failed_budget_possible");
  return end_ok();
}

static int
append_number(int used, uint64 value)
{
  char reversed[20];
  int n = 0;
  do {
    reversed[n++] = '0' + value % 10;
    value /= 10;
  } while (value != 0);
  if (used + n > sizeof(status_data))
    return -1;
  while (n > 0)
    status_data[used++] = reversed[--n];
  return used;
}

static int
budget_status(char *argument)
{
  int gid = 0, length = strlen(argument);
  if (length < 1 || length > 2)
    return end_error("invalid_gid");
  for (int i = 0; i < length; i++) {
    if (argument[i] < '0' || argument[i] > '9')
      return end_error("invalid_gid");
    gid = gid * 10 + argument[i] - '0';
  }
  if (gid >= NGROUP)
    return end_error("invalid_gid");

  struct budget_snapshot state;
  if (budgetstat(gid, &state) < 0)
    return end_error("snapshot_failed");
  uint64 values[] = {state.gid, state.configured, state.remaining, state.max,
                     state.refill_per_100_ticks, state.mode, state.n_allowed,
                     state.n_blocked, state.n_refused};
  int used = 0;
  for (int i = 0; i < 9; i++) {
    if (i != 0)
      status_data[used++] = ',';
    if ((used = append_number(used, values[i])) < 0)
      return end_error("internal");
  }
  if (prefix("STAT") < 0 || write_all(status_data, used) < 0 || emit("\n") < 0)
    return -1;
  return end_ok();
}

int
main(int argc, char **argv)
{
  request_id = "-";
  if (argc != 4) {
    end_error("usage");
    exit(1);
  }
  if (!id_ok(argv[1])) {
    end_error("invalid_id");
    exit(1);
  }
  request_id = argv[1];

  int list = strcmp(argv[2], "list_files") == 0;
  int read = strcmp(argv[2], "read_file") == 0;
  int remove = strcmp(argv[2], "delete_file") == 0;
  int status = strcmp(argv[2], "get_budget_status") == 0;
  if (!list && !read && !remove && !status) {
    end_error("unsupported_tool");
    exit(1);
  }
  if (!status && !path_ok(argv[3], list)) {
    end_error("invalid_path");
    exit(1);
  }
  if (chdir("/") < 0) {
    end_error("internal");
    exit(1);
  }

  int result = list ? list_files(argv[3]) :
               read ? read_file(argv[3]) :
               remove ? delete_file(argv[3]) : budget_status(argv[3]);
  exit(result == 0 ? 0 : 1);
}
