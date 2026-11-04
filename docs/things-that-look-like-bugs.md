# Things that look like bugs

Behavior that reads as broken but is deliberate. If you came here after hitting
something surprising, it may be listed below.

## A killed mutation gate can leave a scratch directory

**What you see:** after forcibly killing `npm run test:mutations`, a
`serp-axi-mutation-*` directory can remain in the system temporary directory.

**Why:** the mutation gate runs mutants in disposable copies, reusing the
installed Python environment without synchronizing it from those copies. A
forced kill can leave a scratch directory behind; it does not strand a mutant
in the checkout. Normal completion removes the copy.

**When this becomes a real bug:** if a run changes checkout source, reads a
browser profile into its copy, or synchronizes the shared environment from a
temporary project.

## Python tests move their temporary directory when TMPDIR is too long

**What you see:** with `TMPDIR` set to a long path (for example under
`$XDG_STATE_HOME`), `pytest`'s `tmp_path` and the mutation gate's scratch
directory appear under `/tmp` instead.

**Why:** the tests bind unix sockets under `tmp_path`, and AF_UNIX allows a
whole socket path only 107 bytes. Pytest's own `pytest-of-<user>/pytest-N/
<test-name>` layout, and the gate's scratch project, already spend most of that
before `.X11-unix/X<n>` is added, so a long inherited `TMPDIR` makes those
tests fail with "AF_UNIX path too long" on clean code. A short `TMPDIR` is still
honored; only one that would not fit falls back to `/tmp`. "Would not fit" is
counted the way pytest builds the path: through symlinks (a short link to a long
directory is long), with the user named `unknown` when the platform has none,
and with room for a six-digit run number, since pytest numbers its runs without
bound. The pytest tree under `/tmp` is deleted when the run ends.
`ladder-cli/tests/test_socket_budget.py` binds real sockets at the boundary.

**When this becomes a real bug:** if a short `TMPDIR` is ignored, if the
fallback lands anywhere other than `/tmp`, if the move happens when an explicit
`--basetemp` was given (the gate passes one and it must win), or if a test
depends on its `tmp_path` being under `TMPDIR` for isolation rather than length.

## `search --provider kagi` ignores `--region` and `--lang`

**What you see:** `--region uk --lang de` changes nothing about Kagi results,
while the same flags visibly change Serper and Bright Data results.

**Why:** Kagi's `/html/search` takes region and language from the signed-in
account's own settings, not from the query string. There is no per-request
override to forward them to. Rejecting the flags outright would mean a caller
could not use one command line across providers, so they are accepted and
documented as having no effect here instead.

**When this becomes a real bug:** if Kagi adds query parameters for region and
language, `searchKagi` should start sending `params.gl` and `params.hl` and this
entry should be deleted.

## An expired Kagi token produces "returned no results", not an auth error

**What you see:** a stale `KAGI_SESSION_TOKEN` fails with `Kagi returned no
results` rather than something naming authentication. The help text mentions an
expired token, which looks like a guess.

**Why:** Kagi answers an unauthenticated `/html/search` with HTTP 200 and a
sign-in page, not a 401 or 403. From the client there is no status code to key
on, so an empty parse is the only available signal, and it genuinely is
ambiguous: a real query with zero results looks identical. The error names both
possibilities rather than asserting the one it cannot verify.

**When this becomes a real bug:** if Kagi starts returning a 401/403 for an
expired session, the existing status branch in `src/kagi.ts` already handles it,
and this entry should be deleted.

## The Kagi provider parses HTML instead of calling an API

**What you see:** `src/kagi.ts` contains regex-based HTML extraction, unlike
every other provider in this repo, which parses JSON.

**Why:** Kagi ships no public search API on an ordinary subscription. The
alternatives were a browser automation dependency or shelling out to a
third-party CLI that parses the same HTML anyway. Both add an install step
without removing the parsing. `src/kagi.test.ts` pins the parser against a saved
real SERP so a Kagi redesign surfaces as a test failure.

**When this becomes a real bug:** if Kagi ships a subscription-accessible search
API, this provider should move to it and this entry should be deleted.

## A `--ladder` timeout does not mean `dead`

**What you see:** a rung that exceeds its 90-second subprocess budget reports
`error` and escalation continues. Exhaustion reports `error` only if the final
rung malfunctioned. A domain that does not resolve reports `dead` immediately.

**Why:** `dead` is terminal on purpose: no browser revives a domain that does not
resolve, so the climb stops. A timeout is our own 90-second budget firing, which
says nothing at all about the page, so it climbs instead. Reporting both as
`dead` would let a blown budget look like a decision about the site.

**When this becomes a real bug:** if a timeout is classified as proof that the
page or domain does not exist, terminating escalation.

## The request cap can interrupt escalation

**What you see:** the parent can raise a request-timeout error before all four
rungs finish, even though each rung has its own 90-second budget.

**Why:** the parent's independent 120-second cap limits the whole request.
It is not a promise of 90 seconds for every rung. On expiry the parent resets
the child so a late reply cannot answer a later request.

**When this becomes a real bug:** if a reply from the abandoned request is
delivered to another request, or a documented whole-climb guarantee replaces
this independent cap without changing its enforcement.

## Ceiling 5 stops at rung 4

**What you see:** `--rung-ceiling 5` can report `rungReached: 4`.

**Why:** the protocol retains ceiling 5, but the live registry contains only
rungs 1-4. Audio transcription helpers exist; browser/audio integration is
deferred. A second headed fetch would add no audio solve, so it is not attempted.
Every live rung keeps the killable subprocess budget.

**When this becomes a real bug:** if audio integration ships without adding a
live rung, or the response claims rung 5 ran when only rung 4 was attempted.

## A timed-out rung can run up to 20 seconds past its budget

**What you see:** a rung with a 90-second budget sometimes returns its `error`
at 90 to 110 seconds, not at 90.

**Why:** the rung's process group gets SIGTERM first and up to
`STOP_GRACE_S` (5 seconds, `ladder_cli/stopping.py`) to stop before SIGKILL.
Rung 4 runs an Xvfb display server. On SIGTERM Xvfb removes its own
`/tmp/.X<n>-lock` and socket; SIGKILL left both behind on every timeout. If it
is still there after the grace period, the group gets SIGKILL and then
`KILL_WAIT_S` (5 seconds) to finish dying; a member in uninterruptible sleep
that survives that raises instead of being called stopped. `_reap` then gives
the pipes `PIPE_DRAIN_S` (5 seconds) and, if a straggler still holds them, kills
the leader and waits `KILL_WAIT_S` once more. So the bound is
90 + 5 + 5 + 5 + 5 = 110 seconds. Each wait ends as soon as its target is gone,
so a rung that stops promptly costs nothing extra. A zombie does not count as
running: under a PID 1 that never waits, a rung's orphaned grandchild stays one
for good.

"Nothing is running" is read off `/proc`, and a scan of it is not atomic: a
child forked and gone again between the scan's reads is in no listing, so a
stop that called the group empty could skip a member it never saw. The last step
covers that. `_stop_group` asks `stopping.stop_with_grace` to send one final
SIGKILL even when the wait said the group was empty, in the routine's own
`finally`, so a SIGTERM landing after the wait cannot skip it. The leader is not
reaped inside the wait (`_reap` does that afterwards) so that its pid stays
allocated, and a pid number is not handed to another process while any task
still uses it as a pid or a group id. That invariant is checked against the real
kernel by `test_an_unreaped_leader_keeps_its_pid_and_group_id_allocated`; the
missed-member kill is
`test_a_member_the_scans_missed_is_killed_before_the_group_is_called_stopped`,
and the raise for a member that survives SIGKILL is
`test_a_group_member_that_survives_sigkill_is_reported_not_called_stopped`.

The full `/proc` scan is the expensive question, so `_stop_group` asks it at
most every 0.2 seconds; between scans the cheap `killpg(group, 0)` asks only
whether the group still exists. `test_a_stubborn_group_is_scanned_for_members_only_a_few_times_a_second`
pins that a stop does not turn into fifty process-table scans. A `/proc` that
cannot be listed, or a scan that classified no process at all, counts as
running, so the grace period decides and not a crash or an early "stopped".

**When this becomes a real bug:** if a stop runs longer than 20 seconds past its
budget, if a group is called stopped while a member is still running, if the
last SIGKILL is sent after the leader has been reaped, or if a timed-out rung 4
leaves a lock behind for a pid that is dead.

## The stop bounds are separate constants, and none has a knob

**What you see:** three waits in the stop paths (`STOP_GRACE_S`,
`PIPE_DRAIN_S`, `KILL_WAIT_S`, all 5 seconds in `ladder_cli/stopping.py`) but
no flag, environment variable or config key for any of them. The parent's
120-second request cap does not wait for them either: it resets the child with
`child.kill()` (`src/ladder.ts:526`, SIGTERM), which `main` turns into
`SystemExit` (`ladder_cli/cli.py:330`), so a stop in progress is interrupted and
finishes through the same `finally` that kills the group.

**Why:** they answer different questions, so one number cannot be right for all
three. `STOP_GRACE_S` is how long SIGTERM gets to clean up; `PIPE_DRAIN_S` is
how long a stopped rung's pipes get to reach end of file; `KILL_WAIT_S` is how
long a target that survived SIGKILL gets to finish dying. Keeping them separate
is what stops a change made for a slow Xvfb from silently changing the other
two bounds. No knob exists because nothing has needed a different value yet; the
house rule is a flag, an environment variable and a config key together, and
adding all three for values no run has had to change would be three new surfaces
to document. They are bounds for something that does not stop when asked, not
measured stop times (`ladder_cli/stopping.py` says so beside them).

**When this becomes a real bug:** if a stop runs longer than the sum of its
bounded waits, if the parent's 120-second cap resets the child during a stop and
the group is left running (read from the code above, not tested end to end), if
someone needs a longer or shorter bound for a real rung and has no way to set one
(then add the triplet), or if the parent's single SIGTERM to the resident CLI is
lost and the CLI and its rung group outlive the parent (the parent has no SIGKILL
escalation; adding one needs a timer value, which is a new tunable).

## A straggler outside the group cannot hang the CLI, and its output is dropped

**What you see:** after a timed-out rung, `_reap` gives `communicate()` the pipe
drain bound and then kills the leader and closes the pipes, even though the pipes
had not reached end of file. Anything the rung printed after the timeout is gone.
If the leader is in uninterruptible sleep and survives that SIGKILL, `_reap`
raises instead of waiting on it forever.

**Why:** `communicate()` returns only at end of file on both pipes. A descendant
that left the group (`setsid`, a double fork) and inherited them holds them open
for as long as it lives, and the group's SIGKILL cannot reach it, so an unbounded
`communicate()` would hold the resident CLI for that long. The wait after the
leader's own SIGKILL is bounded for the same reason. A stopped rung's
output is not used (the result is the budget error), so nothing the CLI reports
is lost. Covered by
`test_reap_does_not_hang_on_a_straggler_outside_the_group_that_holds_the_pipes`
and `test_a_leader_that_survives_sigkill_is_reported_not_waited_on_forever`.

**When this becomes a real bug:** if a rung that finished normally has its
output cut off by this path, or if a timed-out rung's output starts to be used
in the result.

## A rung that exits on its own still has what it started stopped

**What you see:** a rung that was not stopped by the budget has a process it
started in its group killed after it returns, even though `communicate()` came
back normally.

**Why:** the leader exiting says nothing about the group. A child killed by the
OOM killer, a SIGKILL or a native crash cannot run its own cleanup, and an Xvfb
it started keeps its `/tmp/.X<n>-lock` for the life of the machine; that is the
leak this closes. After the normal return, `run_rung_isolated` stops the group
when `/proc` shows a live member, which also proves the group id is still ours.
If nothing is left there, no signal is sent: the leader has been reaped and its
number could otherwise belong to an unrelated group. For the same reason this
stop skips the unconditional last SIGKILL (`leader_reaped`): the leader is
already reaped, so only a group that outlasted the grace period is killed, and
one that stopped on SIGTERM gets nothing more. Covered by
`test_a_rung_that_dies_on_a_signal_has_what_it_started_stopped` and
`test_a_reaped_leaders_emptied_group_is_not_sent_a_last_sigkill`.

**When this becomes a real bug:** if a rung deliberately leaves a background
process to outlive its request (none does), or if a member is killed after the
rung has already stopped it.

## A SIGKILL of the resident CLI leaves its rung group behind

**What you see:** after the resident ladder-cli is killed with SIGKILL (the OOM
killer, an external `kill -9`, or a supervisor timeout), the `--rung` child and
the Xvfb it started keep running, and the display slot stays held.

**Why:** SIGKILL cannot be caught, and the rung is deliberately in its own
session (`start_new_session=True`) so the group stop can reach everything the
rung starts. The budget and SIGTERM paths run that stop; a resident CLI that is
itself killed cannot. A parent-death signal on the rung alone would still leave
the Xvfb it started alive, so closing this needs a supervisor/watchdog or a
parent-death chain through every child, not one more `prctl` in the rung.

**When this becomes a real bug:** if the resident CLI is routinely killed
externally and the leaked process and display slot matter; then add the
supervisor or parent-death chain. Until then, stop the CLI with SIGTERM.

## The display stop and the rung-group stop share a routine and differ in how they wait

**What you see:** `headed._stop_display` and `cli._stop_group` both end in a
call to `stopping.stop_with_grace`, yet each passes its own `wait_gone`, and the
group asks `killpg(group, 0)` every 20 ms while scanning `/proc` at most every
200 ms, where the display's is one `Popen.wait(timeout)`.

**Why:** the order (SIGTERM, wait up to `STOP_GRACE_S`, SIGKILL in a `finally`,
then a bounded wait for the kill) is the part that has to be the same, so it
lives once in `ladder_cli/stopping.py`. A display stop used to carry its own copy
without the `finally`, and a SIGTERM that `main` turned into `SystemExit` during
its wait left Xvfb running; sharing the routine is what removed that. What
cannot be shared is how "gone" is known. The display has a `Popen`, so
`Popen.wait(timeout)` returns the instant it exits. A process group has no wait:
the only question the kernel answers is whether something in it is still there,
so `_stop_group` polls, has to tell a zombie from a running process, and has to
survive a SIGTERM landing mid-wait. The group also needs the kill even when the
poll says empty, because one `/proc` scan cannot see a member forked and gone
between its reads; the display's wait has no such gap, so only the group passes
`always_kill=True`. Giving the display that poll would add a loop where a wait
suffices, and giving the group the display's wait would watch only the group
leader and miss a grandchild removing its own lock. The grace period is one
constant, `stopping.STOP_GRACE_S`, read when the stop runs and not passed in as
a parameter, so there is no second copy to drift.
`test_the_grace_period_is_read_when_the_stop_runs_and_is_not_a_parameter` pins
that, and `test_the_display_waits_for_the_one_grace_period_the_group_stop_uses`
pins that the display's SIGTERM wait is that value and not a copy.

**When this becomes a real bug:** if either stop stops going through
`stop_with_grace` (`test_the_display_and_the_rung_group_are_stopped_by_the_one_routine`),
if a third stop appears that copies the routine instead of calling it, or if a
SIGTERM landing during either wait leaves the server or the group running
(`test_a_sigterm_that_lands_while_the_display_is_stopping_still_kills_it` and the
two real-process SIGTERM tests in `tests/test_cli.py`).

## A display slot with a lock we cannot prove dead is skipped, never reclaimed

**What you see:** `/tmp/.X<n>-lock` files for slots in `:200` to `:699` that
nothing is using, yet the headed rung steps over them. With enough of them it
fails with `no free Xvfb display between :200 and :699`.

**Why:** a slot is taken back only when its lock names a pid that no longer
exists (or a zombie, below) and the lock belongs to the current user. A lock
owned by someone else sits in a sticky `/tmp`, where we cannot remove it, so the
slot is not ours to take.
A lock that is empty, garbled, longer than 64 bytes, names a pid too large to
probe, or is not a regular file at all (a FIFO, a symlink, a directory) is
skipped for the same reason: claiming a slot needs proof, not a lack of proof.
Xvfb writes eleven bytes (`"%10d\n"`, read off a real server's lock on
2026-11-02), so a longer file is not one it wrote, and reading only its first
64 bytes would take the number at the front of it for a server's pid. Such a
lock is never opened in a way that waits, so a FIFO planted in `/tmp` cannot
hang the search. A dead server's pid that the kernel has since handed to
another process also reads as held. A lock for a dead pid that we own is
reclaimed, because Xvfb starts over it (checked against a real server, over both
a leftover lock and its socket), unless something is listening on the slot's
socket. A dead lock beside a live listener is another server's slot: a real Xvfb
started there exits 1 with "server already running" (checked 2026-11-03, with a
stand-in listener on the abstract address), so `display_is_free` connects to
the socket before it calls the slot free. A connect that cannot answer (a
timeout on a full backlog, a permission error) is raised rather than read as a
taken slot, so `free_display` reports the local cause instead of
`no free Xvfb display between :200 and :699`. Both addresses are tried before
that raise, so a file another user left cannot hide an abstract socket that
answers.

A lock naming a zombie is the one held lock that is reclaimed. A real Xvfb
refuses to start over it (rc 1, "Server is already active for display ...
remove /tmp/.X<n>-lock", checked 2026-11-03), and a zombie nobody reaps stays
one: this CLI runs under a PID 1 that may never wait, and an Xvfb that was
SIGKILLed after its rung child was killed too is orphaned to that PID 1.
Nothing else would ever remove its lock, and each one would take a slot for good,
so `free_display` classifies each candidate's lock once (`_lock_state`) and, for a
zombie it owns, removes the lock (`_reclaim_zombie_lock`). A running server,
another user's lock and anything unreadable are left alone. The removal moves the
lock aside first and re-classifies the moved file, so a lock another server wrote
between the read and the removal is never the path that gets unlinked; one that
turns out not to be the zombie is linked back. A lock that goes away while it is
being moved is not an error (`missing_ok`). The owner is checked before `/proc`
is read, so a foreign user's lock costs neither a stat read nor a signal.
`test_only_a_zombies_lock_is_reclaimed`,
`test_a_lock_that_is_replaced_while_it_is_being_reclaimed_is_put_back`,
`test_the_slot_search_reclaims_a_zombies_lock_and_offers_the_slot` and the
real-server `test_a_lock_naming_a_zombie_is_held_until_it_is_reclaimed_and_then_the_real_server_starts`
cover it.

A socket file with no lock and nothing listening does not hold its slot either.
A real Xvfb started over one, wrote its own lock, and removed both on SIGTERM
(rc 0, checked 2026-11-03), and enough such files would have used up the 500
slots. The slot is free unless something answers on the socket
(`test_a_socket_file_with_no_lock_holds_its_slot_only_while_something_listens_on_it`,
and the real-server `test_a_real_xvfb_starts_over_a_socket_file_left_by_a_killed_server`).

When a server we start exits at once, `_await_display` decides whether another
server won the slot by asking `display_is_free`, not by reading the words Xvfb
printed: those change between versions and wrappers, and a miss turned a lost
race for one slot into a failed rung with 499 free. A taken slot moves to the
next slot. A slot that is free again is started once more on the same slot: the
server that won the race may already have stopped, so one retry tells that from
a broken Xvfb, while a second immediate exit on that free slot reports its
stderr and fails the rung.

**When this becomes a real bug:** if a lock we own that names a dead pid is
skipped while nothing listens on its socket, since that is the leak this exists
to close, if the headed rung reports no free display while fewer than 500 slots
hold a live, foreign, or unreadable lock or a live listener, or if a slot
taken by another server fails the rung instead of moving on.

## A rung 4 whose Xvfb survives SIGKILL raises instead of returning its page

**What you see:** a headed fetch that had its page fails with `Xvfb (pid N) did
not exit within 5s of SIGKILL`, and the rung reports `error`.

**Why:** a server in uninterruptible sleep (a `/tmp` on a stalled mount, where it
removes its lock) ignores SIGKILL until the call returns. `_stop_display` waits
for it after the kill, and without a limit that wait would hold the rung's
result for as long as the mount stays stalled. It waits `KILL_WAIT_S` and then
raises, so the failure is named and the rung is not left hanging. The raise
comes out of the `with` block that held the page, so the page is dropped with
it. If the page had already failed, that page error stays the one reported and
the stop failure is added to it as a note (`add_note`), so the rung does not lose
the reason the page failed and the error's own `__cause__` is left alone. Only an
`Exception` from the stop is folded in that way: a KeyboardInterrupt or SystemExit
during the stop still propagates. Covered by
`test_the_kill_is_followed_by_a_bounded_wait_that_names_the_server_it_could_not_reap`,
`test_a_failing_display_stop_does_not_replace_the_pages_error`,
`test_a_failing_display_stop_is_the_error_when_the_page_succeeded` and
`test_an_interrupt_during_the_display_stop_is_not_swallowed`.

**When this becomes a real bug:** if the error is raised for a server that did
exit, or if a rung that has nothing wrong with its display reports it.

## Rung 4 treats a display as ready when its lock names the server and a connect succeeds

**What you see:** `_await_display` waits 1.5 seconds before its first look, then
returns only once `/tmp/.X<n>-lock` holds the pid of the Xvfb we started and a
connect to the display's socket succeeds. A lock that names our pid but a
socket that refuses keeps it waiting, up to 10 seconds.

**Why:** Xvfb writes its lock before it binds its socket. Of 200 real starts on
2026-11-03, 39 showed the lock first, by 0.012 to 0.071 ms on an idle machine,
so the lock alone says "claimed", not "ready". The 1.5-second settle makes that
gap unlikely to matter and does not make it impossible. Both addresses are
tried because Xvfb listens on the socket file and on the Linux abstract socket
of the same name, and where it cannot create the file (an unwritable
`/tmp/.X11-unix`, which it tolerates; checked 2026-11-03) only the abstract
one exists. The probe connects and closes without sending anything; the server
drops a client that never sends its setup request. The lock still has to name
our pid: a slot reclaimed from a dead server holds the old pid until the new
one rewrites it. After the first second the poll interval backs off from 50 ms
to 250 ms, so a live server that never writes its lock costs tens of reads
rather than ~170. A connect failure that is not "nothing there" is raised at
once instead of being retried until the deadline and then blamed on the
server, because it is a local fault (a full backlog, an unwritable socket
directory) and the message must say so.

**When this becomes a real bug:** if a headed fetch fails to connect to its
display right after `_await_display` returned, or if the probe leaves a client
connected that makes a server hold a slot after the rung is over.

## The real-Xvfb tests clean up with a read and then an unlink

**What you see:** `_remove_own_leftovers` in `tests/test_rungs_headed.py` reads
a slot's lock, finds its own test server's pid, and then unlinks the lock and
the socket as two further steps. If another process replaces the lock between
the read and the unlink, the replacement loses it.

**Why:** a file system has no "remove this if it still says X". The two ways
to narrow the gap each leave one of their own. Comparing the inode before the
unlink still has a window between the compare and the unlink. Renaming the lock
aside first, then checking it, then deleting the renamed file, moves a lock that
may belong to someone else for as long as the check takes, and a server that
looks for its lock in that time finds none. `/tmp` is mode 1777 (sticky), so
another user cannot replace or remove a file this user owns, and only a process
of the same user can race the unlink; that, and the fact that the slot came
from `free_display` a moment earlier, is why the gap needs a same-user process
to take that exact slot between two system calls. That reasoning is from
reading the code and the directory mode, not from a test that races it. This
is test cleanup and not library code, which is why the pattern lives in the
test file.

**When this becomes a real bug:** if a library function goes back to reading a
lock and then unlinking that original path (the library's reclaim moves it
aside and re-checks what it moved), or if a run of the suite is seen removing
another process's lock.

## A profile lock whose owner cannot be checked is kept

**What you see:** `clear_locks` raises `profile lock owner cannot be checked` and
leaves `SingletonLock`, `SingletonCookie` and `SingletonSocket` in place when
`/proc/<pid>/stat` has no entry but signal 0 still finds the pid.

**Why:** a missing `/proc` entry can mean the browser exited, or that this host's
`/proc` does not cover the pid (a chroot, a minimal image, a mount elsewhere).
Only signal 0 saying GONE proves the owner exited; anything else is unknown, and
clearing the locks would start a second browser on a profile that is still in
use. The stat line is read once and decides; signal 0 is asked only when the
stat is missing, so a pid reused between two lookups cannot turn a stale lock
into a running owner. A pid that is a zombie is still cleared, because the stat
line says `Z`.

**When this becomes a real bug:** if a launch is blocked for good by a lock
whose owner is gone, or if the refusal is raised when the stat line was readable.

## Old working-directory profiles are not picked up automatically

**What you see:** after upgrading, an existing `profiles/` folder beside the
CLI remains on disk, but the browser starts without that folder's warm state.

**Why:** profile storage now uses `$XDG_STATE_HOME/serp-axi/profiles`, with
`~/.local/state/serp-axi/profiles` as the fallback. State is independent of the
launch directory. Old folders are neither imported nor deleted automatically.

**When this becomes a real bug:** if changing the launch directory changes the
profile root without changing `XDG_STATE_HOME`, or an upgrade deletes old state.

## Jar flags do nothing when HTTP or Camoufox answers

**What you see:** a successful scrape through rung 1 or 2 leaves `--jar-out`
unwritten, even when `--cookie-state jar` is set.

**Why:** only zendriver rungs 3 and 4 load and save the filtered jar. Success at
an earlier rung ends escalation; jar flags do not force a later browser launch.

**When this becomes a real bug:** if zendriver succeeds with `jarOut` set but
neither saves the jar nor reports a write error.

## Each zendriver rung loads and saves its own jar

**What you see:** when escalation reaches both zendriver rungs, each reads
`jarIn` before navigation and writes `jarOut` before shutdown. The later save
replaces the earlier one. Explicit paths are not renamed to `.cookies.json`.

**Why:** the rungs run in separate processes with separate browser profiles.
The jar paths are per-request inputs and outputs, not a shared browser context.
Use distinct JSON paths from zendriver's `.cookies.dat` pickle files; an
explicit output path is overwritten as supplied.

**When this becomes a real bug:** if the documented contract changes to carry
the previous rung's output forward automatically, or a rung writes outside
the supplied output path.

## Jar export can fail after page extraction succeeds

**What you see:** a zendriver rung reports an error after extracting a page when
its requested `jarOut` cannot be saved.

**Why:** the requested export is part of the result. Returning success would
hide a missing or stale jar from the caller. Atomic replacement also requires
write access to the target's parent directory, even when the old file is writable.
A symlink output keeps the link and replaces its resolved target.

**When this becomes a real bug:** if the rung reports success without completing
the requested export, destroys the old jar on a failed write, or replaces the
symlink itself.

## `--include-markup` does almost nothing for Serper and `--ladder`

**What you see:** `serp-axi scrape <url> --include-markup` and the same command
without the flag print the same record, apart from the rerun command in `help`,
which carries the flag whenever it is on.

**Why:** both paths build a record with no raw-HTML field. Serper's record is
`url`, `title`, and `text`, taken from the response by name in
`src/commands/scrape.ts`, so nothing else in the response reaches the output.
Ladder rung 1 strips tags and then decodes entities (`extract_html` in
`ladder-cli/ladder_cli/rungs/http.py`), and the browser rungs read
`document.body.innerText`. The one field the flag can change is `title`, when it
is itself a whole HTML document. The flag is accepted everywhere so one command
line works across providers, and every provider goes through
`shapeScrapeRecord`.

**When this becomes a real bug:** if Serper or ladder starts returning a field
whose name ends in `html`, and it shows up in the output without
`--include-markup`, or if `--include-markup` is rejected under one provider.

## The `includeMarkup` config key is read for Bright Data only

**What you see:** `"includeMarkup": true` in the config file keeps raw-HTML
fields in a Bright Data run, but a Serper or `--ladder` run ignores it, and a
malformed value (`"includeMarkup": "yes"`) fails a Bright Data run and passes the
other two.

**Why:** Bright Data is the one provider whose records carry raw-HTML fields of
their own, so it is the only path that asks the config what `includeMarkup`
says. Every path does open the file now, for the `maxChars` and `fullMaxChars`
keys (see "Every scrape path opens the config file, after its input checks"
below), but a Serper or `--ladder` run never looks at the `includeMarkup` key, so
a malformed one still passes there. The flag and `SERP_AXI_INCLUDE_MARKUP` are
read for every provider, and they win over the config key.

**When this becomes a real bug:** if a Bright Data run ignores the config key
when neither the flag nor the env var is set, or if a run reads the config file
before it has checked its URL and API key.

## `runSearch` with no config argument reads the real config file, and a bad file stops a flags-only searxng run

**What you see:** a test or script that calls `runSearch(args, fetchImpl, env)`
without the fourth argument gets the config file from `env`'s
`XDG_CONFIG_HOME`, or from the process's home directory when that is unset. It
does not get an empty config. A searxng run also reads the file before it looks
at flags, so a corrupt `config.json` fails `--provider searxng` even when
`--searxng-url`, `--engines`, and `--search-timeout-ms` are all given, and it
replaces the error for a bad `--searxng-url`. Injecting `HOME` in the env has no
effect on where the file is looked for.

**Why:** the CLI entry point passes no config, so the default has to be the real
file. Tests pass `{}` to opt out. Making the read lazy, or taking the home
directory from the handed env, would change what `serp-axi search` does on a
broken file, and `runScrape` has the same read (`config ?? loadStoredConfig(...)`
in `src/commands/scrape.ts`), so the two should change together. Serper,
Bright Data, and Kagi runs never open the file, and flag errors such as
`--num 0` are reported before it is opened. Both are pinned by tests in
`src/commands/search.test.ts`.

**When this becomes a real bug:** if a non-searxng run opens the config file, if
a flag error is replaced by a config error for a flag checked before the load,
or if a test that hands in a config still reads the developer's own file.

## A hint's rerun command repeats flags, not env or config settings

**What you see:** the command in `help` has `--include-markup`, `--dataset-id`,
or a ladder axis flag only if that flag was on the command line. A value that came
from `SERP_AXI_INCLUDE_MARKUP`, `BRIGHTDATA_DATASET_ID`, or the config file is
not repeated, except that `--include-markup` is added whenever markup is on,
whichever way it was turned on. The `--include-markup` hint also repeats the cap
flags as typed (`--max-chars 500`, or `--full --full-max-chars 7000`), and the
`--full` hint does not: it repeats nothing of `--max-chars`, because `--full`
refuses it. A cap that came from `SERP_AXI_MAX_CHARS`, `SERP_AXI_FULL_MAX_CHARS`,
or the config file is never repeated.

**Why:** the env and config settings apply to the rerun by themselves, in the
same shell. The hint is shorter, and a pasted command does not pin a value that
the reader may have changed. A typed cap flag is the one flag-only setting that
changes what the rerun returns without changing which record it fetches, so
dropping it from the markup hint would bring the markup back under a different
cap than the reader chose. The cap flags are repeated only after they passed the
whole-number check, so they need no shell quoting.

**When this becomes a real bug:** if the rerun fetches a different dataset, or
uses different ladder axes, than the run that printed it, with the same
environment; or if the `--include-markup` hint drops a cap flag the run was
given, or the `--full` hint carries `--max-chars`.

## Kept text fields can still contain tags, and `markdown` and `html2text` can repeat each other

**What you see:** a Bright Data record keeps both `markdown` and `html2text`,
which carry nearly the same text. A page about HTML can show a literal `<div>`
in a field that stayed.

**Why:** the omission rule looks at a field's name (ending in `html`) and at
whether its whole value is an HTML document. It does not rewrite the inside of a
field that stays. A regex tag-stripper would delete the `<div>` a page is
legitimately talking about, and ladder rung 1 decodes entities after it removes
tags, so a tag in its text is content. Dropping
`html2text` to save space would also be a guess about which field a caller reads.
The two are not copies. A development scrape of `https://example.com` on 2026-11-03
returned the same sentence in both, with `html2text` hard-wrapped at a line width
(a `\n` mid-sentence); that observation was not recorded in this repo, so treat the
exact wrap as unverified. The recorded fixture in `src/fixtures/` differs in markup
style (`# Example Domain` against `EXAMPLE DOMAIN`) and has no mid-sentence wrap.

**When this becomes a real bug:** if a field whose name ends in `html`, or whose
value is a whole HTML document, appears in the output without
`--include-markup`.

## A record whose only text is an HTML document keeps it

**What you see:** a Serper or ladder `text` that begins with `<!doctype html>`
comes back, cut to the character limit, with no `markupOmitted` entry. A Bright
Data record with `page_html` and nothing else textual does the same. The same
`page_html` next to a `markdown` field is left out.

**Why:** the rule is "omit markup unless it is all there is to show". When every
text field the limit applies to is markup, omitting them would turn "the page
came back as HTML" into an empty result with a hint to rerun for the thing that
was just dropped. Showing the document, bounded by the limit, is the more honest
failure. Markup outside that scope (a Serper `title`) is still omitted, because
nothing would bound it.

**When this becomes a real bug:** if a markup field is kept next to a field of
real content, or if the only text a record has is dropped.

## Prose that opens with a literal `<html>` is classed as a document

**What you see:** a Bright Data field named `summary` whose value is
`<html> is the root element` appears in `markupOmitted`, while the same text in
a field named `snippet` that begins `<div>` is kept.

**Why:** the document test looks only at how a value opens: a doctype or an
`<html` tag, after any whitespace, comments, and XML prologs. That is cheap and
cannot be fooled into a slow scan on a large page (the scan is linear; a test
pins it). It cannot tell a page from a sentence that starts with the same
characters, and a `<div>` fragment under a name that does not end in `html` is
treated as content for the same reason: nothing here parses HTML. The omission
is not silent, so `--include-markup` brings the field back.

**When this becomes a real bug:** if a field that stays contains a whole
document (starting with a doctype or `<html>`), or if an omitted field is not
named in `markupOmitted`.

## Serper and ladder `title` and `warning` are not cut to the limit

**What you see:** with the default 1,200-character limit, a Serper or ladder
record can still print a `title` (or the ladder's `warning`) longer than that,
and no `truncatedFrom` marker covers it.

**Why:** the limit is a bound on the page body. Serper and ladder each declare
one body field, `text`, and the limit applies to that field only. A title is
expected to be short, and so is the ladder's `warning`, a message the child
writes by protocol. The `warning` is attached after the record is shaped
(`src/commands/scrape.ts`, after `shapeTextRecord`), so it rides outside the
limit. Bright Data's every-string scope has
no such carve-out because its record shape is not ours to know.

**When this becomes a real bug:** if a title or warning large enough to matter
shows up in practice, since that would mean the premise (short strings) is
false and the scope needs to widen.

## A document with a comment or XML prolog before the doctype is still a document

**What you see:** a field that starts with `<!-- saved from url=... -->` or
`<?xml version="1.0"?>` and then `<!doctype html>` is omitted as markup, even
though its first characters are neither.

**Why:** saved pages and some proxies prepend those. The scan skips whitespace,
comments, and prologs before it looks for the doctype, one at a time, so a page
with many comments costs time proportional to its length.

**When this becomes a real bug:** if an unterminated comment or prolog makes the
scan run past the end of the value, or the scan's time grows faster than the
value's length.

## There is no flag to turn markup back off

**What you see:** with `"includeMarkup": true` in the config file, no CLI flag
switches it off for one run.

**Why:** the flag is presence-only like the other boolean flags in `scrape`, so
`--include-markup` can only turn it on. `SERP_AXI_INCLUDE_MARKUP=0` is the
per-run override: env outranks config.

**When this becomes a real bug:** if the env override stops beating the config
key, or `SERP_AXI_INCLUDE_MARKUP=0` is read as true.

## A bad `--full` cap fails a run that never uses `--full`, but not the other way round

**What you see:** `SERP_AXI_FULL_MAX_CHARS=abc serp-axi scrape <url>` exits with a
usage error naming `SERP_AXI_FULL_MAX_CHARS`, though the run never asked for
`--full`. The reverse is not true: `SERP_AXI_MAX_CHARS=abc serp-axi scrape <url>
--full` runs, because a `--full` run never reads the normal cap. A bad `maxChars`
in the config file is skipped the same way. Only the source that wins for each cap
is checked, so a bad env value under a flag, or a bad config value under an env
var, never fails anything.

**Why:** the rerun hint under a truncated field prints the real `--full` cap
("to see up to 8000 characters"), so a normal run has to resolve it. A hint that
printed a number nobody validated would be a wrong fact, and resolving the cap
lazily would make the failure depend on whether the page happened to be long
enough to truncate. A `--full` run prints no hint that names the normal cap, so
it has nothing to validate. That also keeps the `--full` rerun that a hint
offers working when the original run got past a bad `SERP_AXI_MAX_CHARS` with a
`--max-chars` flag.

**When this becomes a real bug:** if a value that loses to a flag or an env var
is checked and fails the run, if a malformed cap passes and a hint prints it, or
if a `--full` run fails on `SERP_AXI_MAX_CHARS` or `maxChars`.

## `--max-chars` is refused with `--full`, and the `--full` hint never offers `--max-chars`

**What you see:** `serp-axi scrape <url> --full --max-chars 500` exits with
"--max-chars cannot be combined with --full", and `--full-max-chars 500` without
`--full` exits with "--full-max-chars only applies with --full". The rerun hint
says `Run \`serp-axi scrape '<url>' --full\` to see up to N characters` and
leaves `--max-chars` off, even when the run being repeated used it. An env var or
config key for the cap that the run does not use is not a conflict:
`SERP_AXI_FULL_MAX_CHARS` on a normal run is still checked (see the entry above),
and `SERP_AXI_MAX_CHARS` on a `--full` run is not read at all.

**Why:** `--full` picks which cap applies, so `--max-chars` beside it would name
a cap the run does not use, and `--full-max-chars` alone would be read by
nothing. Accepting either and ignoring it is the silent failure the other
flag-conflict checks in `scrape` already refuse. Env and config settings are not
conflicts because they are standing defaults for both modes. The `--full` hint
omits `--max-chars` because the rerun is the `--full` run, where `--max-chars` is
an error; the `--full` cap it prints is the one that rerun will use.

**When this becomes a real bug:** if a hint suggests a command that exits with
the usage error above, or if a conflicting pair reaches the network.

## Every scrape path opens the config file, after its input checks

**What you see:** a corrupt or unreadable `config.json` now fails a Serper scrape
(it used to be read only by `--ladder`, and by Bright Data when the flag and env
var had not settled `includeMarkup`). A Bright Data run with `--include-markup`
fails on it too. A bad URL, a missing API key, or a bad cap flag is still
reported as itself, ahead of the file error. A malformed cap is checked after
the URL, provider, axis and ladder checks, so it cannot mask one of those; it is
still checked before the file is opened.

**Why:** `maxChars` and `fullMaxChars` apply to every path, so every path needs
the file. It is read once, after the URL and key checks, so a broken file never
replaces a more useful error. Unlike `includeMarkup`, these keys cannot be left
out of a path. The file is opened even when a flag or env var already settles both
caps, because skipping the read in that case would make a corrupt file fail a
run only when the settings happen to leave a cap open, which is harder to
diagnose than failing every run the same way.

**When this becomes a real bug:** if a run opens the config file before it has
checked its URL, its API key (or ladder binary), and the cap flags, or if a
path opens it twice.

## The Bright Data cap is applied after the records arrive

**What you see:** `serp-axi scrape --provider brightdata --max-chars 5` sends
Bright Data no limit of any kind (the request body is `{"input": [...]}`,
nothing else). Whatever comes back is cut afterward: every long top-level
string except `url` is cut to 5 characters. The cap shortens the output, and
nothing in the request asks Bright Data to send less.

**Why:** the only limit the `/datasets/v3/scrape` reference names is
`limit_per_input`, and it counts records per input, for discovery requests
("Maximum records returned per input", schema `minimum: 1`). It is not a
character limit. An earlier version sent the character cap in it anyway. Sent as
a record count, `--max-chars 5` would have asked a discovery dataset for five
records. The documented fields are `input`, `limit_per_input` and
`custom_output_fields`; none limits the length of a string. Source:
`https://docs.brightdata.com/api-reference/web-scraper-api/synchronous-requests`,
read 2026-11-02. The cap is applied locally in `shapeScrapeRecord`.

**What the download is bounded by instead:** the byte cap in `src/body.ts`
(`DEFAULT_MAX_RESPONSE_BYTES`, 64 MiB; `--max-response-bytes`,
`SERP_AXI_MAX_RESPONSE_BYTES` or `maxResponseBytes` to change it). The old
`limit_per_input` carried the character cap (1200 by default, 50000 with
`--full`; `DEFAULT_MAX_CHARS` and `DEFAULT_FULL_MAX_CHARS` in
`src/scrape-output.ts`), so by default it also told a discovery dataset to
return at most 1200 records per input. That was an accident of reading a record
count as a length, not a bound anyone chose. The request `scrapeBrightData`
builds has only `dataset_id`, `notify` and `include_errors` in its query string
(asserted in `src/brightdata.scrape.test.ts`), so it is not a discovery request
and the field had no records to limit. That is read from the reference, not
tested against the live endpoint. The byte cap is what keeps a large reply out of memory, and it stops
the read, not just the output.

**When this becomes a real bug:** if Bright Data adds a field-length limit to
this endpoint, the download could shrink and this entry should go. Or if a live
request shows the endpoint rejecting a body that holds only `input`; the opt-in
live test (`SERP_AXI_LIVE_BRIGHTDATA`) sends exactly that. Or if a normal scrape
starts hitting the byte cap because a dataset returns many records per URL, in
which case a record limit that is chosen on purpose, not borrowed from the
character cap, belongs in the request.

## The Bright Data cap covers top-level strings, not nested ones

**What you see:** a Bright Data record with a long string inside a nested object
or an array (`{"reviews": [{"text": "<50,000 characters>"}]}`) comes back with
that string whole, under the 1,200-character default, and no `TruncatedFrom`
marker names it. A long top-level string in the same record is cut.

**Why:** the cut walks the record's own entries and cuts each value that is a
string (`shapeScrapeRecord` in `src/scrape-output.ts`). It does not descend into
objects or arrays, because the shape of a Bright Data record depends on the
dataset and is not ours to know, and a marker such as `reviews[3].textTruncatedFrom`
has no obvious home in the output. Only `url` is exempt from the top-level cut,
so that it stays usable as a link. The cap is a bound on the fields a record is
known to hold, not a promise about its total size.

**When this becomes a real bug:** if a dataset puts its page text in a nested
field and a normal run returns it uncapped, since the cap would then fail at what
it is for. The fix is to descend, with a marker that names the path.

## A cut can come out one character short of the cap

**What you see:** `--max-chars 3` on a field that starts `ab` followed by an emoji
returns `ab` (two characters), not three, and the marker reports the real total.
With `--max-chars 1` on a field that starts with an emoji, the field comes back
empty.

**Why:** the cap counts UTF-16 code units, like JavaScript's string length, and an
emoji or other character outside the Basic Multilingual Plane takes two of them.
A cut between the halves would leave half a character, which Node writes to
stdout as the replacement character U+FFFD. `truncate` in
`src/output.ts` backs up one unit instead. The `totalChars` it reports stays in
code units, so it can exceed the number of characters a reader counts.

**When this becomes a real bug:** if a cut field ends in half of a surrogate pair,
or if backing up removes more than one unit.

## Every response read goes through body.ts

**What you see:** `npm run guard` (and CI, and the pre-commit hook) fails on a
bare `response.text()`, `.json()`, `.arrayBuffer()`, `.blob()`, `.formData()` or
`.bytes()` anywhere in `src/`, on any `.body` read (member access, subscript, or
destructuring), and on an import or re-export of `node:http`, `node:https`,
`node:http2` or `undici`. `src/body.ts` and the `*.test.ts` files are exempt. One
line in production code carries a bypass: `JSON.parse(envelope.body)` in
`src/brightdata.ts`, where `body` is a string field of Bright Data's parsed reply
and not a stream.

**Why:** the belief is that no network response is read into memory without a
byte bound. A scan of the tree before the fix (commit `4606e31`) found nine
unbounded reads across Serper, Kagi, SearXNG and Bright Data, so the fix was a
bounded reader (`readBodyText`) and a rule that makes the next unbounded read
fail the build. Three rules cover three
routes: the method names, the `.body` stream (a `for await` loop, `getReader()`,
a stream handed to another function), and a second HTTP client that would never
call `fetch` at all. A rule that reports a warning would be read once and then
ignored, so all three are errors, and `--error=unused-suppression` makes a stale
bypass an error as well.

The rules match names, not types. ast-grep cannot tell a `Response` from another
object with a `.text()` method or a `body` field, so a false positive takes a
bypass with the reason written next to it (`// ast-grep-ignore: <rule-id>
(<reason>)`, on the line above or at the end of the line). The reason sits in
parentheses because the pre-commit dash gate rejects a double hyphen, the
separator ast-grep's own examples use; ast-grep 0.44.1 reads the rule id and
ignores the rest. They also miss method reads that never name the method at the
call: `response["text"]()`, `const { text } = response`, and `const read =
response.text; read.call(response)` all pass. That is a deliberate limit. The
risk being guarded is a developer or an agent copying `response.text()` into a
new provider, and a rule written to stop a deliberate evasion would flag ordinary
code to do it. The `.body` stream is different: a subscript or a destructuring
pattern is a plausible way to reach it, so those spellings are covered.

The guard covers HTTP responses only. `src/ladder.ts` reads a local child's
stdout, not a `Response`, and bounds it by its own check: the pending line may not
pass the same cap (see "The ladder cap bounds the child's read and its reply
line" below). No ast-grep rule watches that read; `src/ladder.test.ts` does.

`src/guards.test.ts` runs each rule against code it must catch, code it must
leave alone, and the bypass forms, and it fails if a rule file has no case that
makes it fire.

**When this becomes a real bug:** if `unbounded-response-read` or
`response-body-stream-access` flags code that is not a response and the bypass
count in `src/` grows past a handful, since the rule would then be teaching people
to type the bypass. Or if a provider reads a body without a hit from any rule, or
`npm run guard` can pass on a tree that has a bare `response.text()`.

## A response over the byte cap is an error, never a partial result

**What you see:** a response larger than `--max-response-bytes` (default 64 MiB)
stops the run with `<provider> response is larger than the <n> bytes serp-axi
will read`, naming the flag, the env var and the config key, and saying that the
key is read by `scrape` and `search --provider searxng`. No results are
printed, even when the first megabyte of the body held a whole valid answer.

**Why:** a JSON document cut off at a byte boundary does not parse, and a cut-off
page of text looks complete and is wrong. The character caps (`--max-chars`)
shorten text on purpose and mark each cut with a `<field>TruncatedFrom` count;
the byte cap protects memory and has no such marker, so it refuses instead. A
`content-length` over the cap is refused before a byte is read, unless the
response is compressed: then the header counts wire bytes rather than the
decoded ones the cap measures, so only the read can decide. Without a usable
header the read stops the moment the running count passes the cap.

**When this becomes a real bug:** if an over-cap body ever produces output from
part of it, or if the error does not say how to raise the cap.

## The byte cap counts decoded bytes, and an error body is cut at 64 KiB, not refused

**What you see:** a gzip reply of 1 MiB that expands to 100 MiB is refused at the
default cap, though only 1 MiB crossed the network (`src/body.socket.test.ts`
serves exactly that over a real socket). Separately, an error response longer
than 64 KiB is not an error of its own: only its first 64 KiB is read when the
CLI quotes it. An unmapped Kagi or Serper status, a Bright Data 400 or unmapped
status, and a Bright Data dataset-scrape 401/403 put the start of that text in
the failure message, shortened again by `boundedDetail`. Kagi's mapped 401/403,
429 and 5xx throw before reading the body at all. Serper reads an error body only
for a status it does not map: the mapped 403, 429, 404 and 5xx branches decide
from the status alone and hang up on the body unread. An unmapped body cut at
64 KiB no longer parses, so that status reports `no details`. If an error body cannot be read at all, the message
says `(the response body could not be read: <reason>)` where the server's text
would have gone, and Serper's JSON parse of that sentence fails the same way.

**Why:** `fetch` undoes gzip and brotli before the stream hands over any bytes,
so the count sees the expanded size, which is what costs memory and what a
compression bomb attacks. A compressed response's `content-length` counts wire
bytes, so it is not compared with the decoded cap; the read still enforces the
cap. An error body only explains a status code the run has already failed on, so
cutting it loses little and refusing it would replace a useful failure with a
less useful one. A mapped Serper status does not need the body at all, so reading
it would delay the error and do I/O for nothing. The marker keeps a failed read
from looking like a server that said nothing. SearXNG reads no error body at all;
its errors come from the status code, and it hangs up on the body before
throwing.

**When this becomes a real bug:** if the count uses compressed bytes, if an error
body read can throw past the status-code failure it was explaining, or if the
failed-read marker is empty.

## The `maxResponseBytes` config key is read for scrape and searxng search only

**What you see:** `"maxResponseBytes": 1000` in the config file caps every
`scrape` run and every `search --provider searxng` run, but a `search --provider
serper`, `kagi` or `brightdata` run ignores it, and a malformed value
(`"maxResponseBytes": "big"`) fails the paths that read it and passes the rest.
`--max-response-bytes` and `SERP_AXI_MAX_RESPONSE_BYTES` apply to all of them.
The overflow error names the config key only for the paths that read it, so a
Serper search's advice does not send its reader to a key that cannot affect the
run.

**Why:** searxng is the one search path that opens the config file, for its URL,
engines and timeout. The other search providers are configured by flag and env
var alone, and making them open the file for one key would put a corrupt
`config.json` in the way of a Serper search that never needed it (see "`runSearch`
with no config argument reads the real config file" above). It is the same shape
as the `includeMarkup` key.

**When this becomes a real bug:** if a search provider starts opening the config
file for another reason, since the key should then apply to it too, or if a path
that does read the key lets a bad value through.

## The ladder cap bounds the child's read and its reply line

**What you see:** two different failures share the one cap.

A page whose HTTP body is over the cap stops inside the ladder child, which
reports `ladder response is larger than the <n> bytes serp-axi will read`; the
run fails with the ladder verdict `error` rather than printing part of the page.
The child did not read the whole body into memory first.

A reply line that is over the cap even though the page body was under it fails
differently: `ladder scrape failed: ladder-cli printed a line longer than <n>
bytes, which serp-axi will not read`. The same run with a larger cap succeeds.
A malformed `SERP_AXI_MAX_RESPONSE_BYTES` or `maxResponseBytes` stops a
`--ladder` run too, as it stops every other scrape.

**Why:** the child reads the network itself, so it cannot rely on the parent's
line check, which only runs after the page has been serialized. The parent sends
its resolved cap as `maxResponseBytes` on the request (protocol 4), the rung
hands it to the isolated child as `--max-bytes`, and the HTTP rung reads the
body with primp's `iter_bytes` instead of `response.text` or `response.json`.
The running byte count is checked before each chunk is kept, and the response is
closed the moment it passes, so the child holds at most the cap plus one chunk
of a runaway page.

The parent keeps its own check because the two measurements are not the same
size. The ladder CLI prints each reply as one JSON line: the text after JSON
escaping, plus the title, the links and the rung metadata. A quote or a newline
in the page costs two bytes; a non-ASCII character costs its UTF-8 width, because
the ladder CLI writes with `ensure_ascii=False` (`ladder-cli/ladder_cli/cli.py:256`).
A page can therefore fit under the body cap and still produce a line over it.
Every line in a chunk is measured before the chunk is appended, against the
bytes already pending for the line it extends, and a child over the line cap is
killed and respawned by the next fetch, because a cut-off line cannot be parsed.
Measuring every line matters when a chunk begins with a newline (a blank startup
line, or the end of the previous reply): checking only the first line would count
zero bytes and let the reply after it through. The same cap bounds the startup
output before the ready line, so a child that prints without ever ending a line
is stopped too. This is a different thing from `--max-chars`, which trims text
after it has been read.

**When this becomes a real bug:** if a body under the cap still fails with the
child's `larger than` error, or if the child returns a page after reading more
than the cap (the read lives in `_read_body` in
`ladder-cli/ladder_cli/rungs/http.py`), or if a page that fits under the cap as
plain text fails on the parent's line check and the line is not over the cap by
that count (the byte count lives in `onStdout` in `src/ladder.ts`, and
`src/ladder.test.ts` pins it at the cap and one byte under), or if a malformed
cap fails a run before the URL, the binary or the other flags have been checked.

## Test-only modules are left out of the package by name

**What you see:** `src/live.ts`, `src/fixtures.ts` and `src/error-assertions.ts`
are compiled into `dist/`, and `package.json` `files` lists `!dist/live.js`,
`!dist/fixtures.js` and `!dist/error-assertions.js` so the published tarball has
none of them. A new test helper that is not added to that list ships.

**Why:** `files` takes `dist` minus `*.test.js`, and a helper that tests import is
not named `*.test.ts`. `live.js` was shipping before this was noticed. A test in
`src/guards.test.ts` finds every non-test module that only test files reach,
following a helper through another test-only module, and fails unless `files`
excludes it, so the list cannot fall behind unnoticed.

**When this becomes a real bug:** if `npm pack --dry-run --json` lists a file
that only tests use, or if the packaging test passes with a helper missing from
`files`.

## A Bright Data hint can say "Rerun this scrape with --full" and print no command

**What you see:** most truncation hints read ``Run `serp-axi scrape '<url>'
--provider brightdata --full` to see up to 50000 characters``. For some records
the hint reads `Rerun this scrape with --full to see up to 50000 characters`
and shows no command.

**Why:** the command names the record's `url`, then the url this scrape asked for
(`input.url`, which Bright Data echoes back). A record that carries neither has no
honest url to print. The hint used to print `'<url>'` there, a command the reader
could not paste and run, so it now names the flag and leaves the command out
(`recordUrl` in `src/commands/scrape.ts`).

**When this becomes a real bug:** if a record that does carry `url` or `input.url`
gets the command-less wording, or if a `<url>` placeholder reaches any hint again.

## The shell-sensitive tests run again with poisoned settings

**What you see:** `npm run check` and CI run the full suite once as `npm test`,
then rerun only the test files that can see the shell as `npm run
test:hostile-env`. The rerun has `SERPER_API_KEY`,
`SERP_AXI_MAX_RESPONSE_BYTES`, the `SERP_AXI_LIVE_*` opt-ins and every other
variable the source reads set to `/nonexistent/serp-axi-hostile-env`, and an
empty `HOME` and `XDG_CONFIG_HOME`, so it cannot read the developer's real
config file either. The 10 live tests are skipped in both runs.

**Why:** the first run cannot see a test that reads the developer's shell or
config. A clean runner has none of those variables and no config file, so a test
that forgot to hand `runScrape` or `runSearch` its own env passes there and fails
on a machine that exports a key. That happened twice before the second run
existed: `searxng.test.ts` failed 24 of 48 tests under an exported
`SERP_AXI_MAX_RESPONSE_BYTES`, and two `scrape.test.ts` tests read the shell and
the real config file. The variable names are scanned from `src/` by
`scripts/hostile-env.mjs`, so a new setting is poisoned without an edit. The
files are found from the import graph: a test that names `process.env` or reaches
a module that does is run, and the real-socket and ast-grep suites that cannot
see the environment are not run a second time.

**When this becomes a real bug:** if the second run passes while a test still reads
the shell (a variable under a prefix the script does not scan: add the prefix to
the shared list in `scripts/env-prefixes.mjs`, which both the script and
`src/searxng.test.ts` import), if a shell-sensitive test is not selected by the
import graph, or if the script reports a clean run after finding no names or no
test files to run (it exits 2 instead).
