import subprocess
import multiprocessing
import argparse
import os
import functools
import sys
import json
import time
from datetime import datetime, timezone
from pathlib import Path


def is_available_repo(root: str, name: str):
    return os.path.isdir(os.path.join(root, name)) and not name.startswith(".")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def result_csv_path(path: str):
    repo = os.path.basename(path)
    return os.path.join(path, f"{repo}_results_w_exact.csv")


def has_completed_score(path: str):
    return os.path.isfile(result_csv_path(path))


def evaluate_repo(path: str, uid: int, gid: int, user: str):
    repo = os.path.basename(path)
    started_at = utc_now()
    started_monotonic = time.monotonic()

    commands = [
        "docker",
        "run",
        "-i",
    ]
    if sys.platform == "linux":
        commands.extend([f"--user", f"{uid}:{gid}"])
    commands.extend(
        [
            f"--rm",
            # fmt: off
            f"--mount", f"type=bind,source={os.path.realpath(path)},target=/mnt/{repo}",
            f"--security-opt", "seccomp:unconfined",
            # fmt: on
            f"typybench-{repo.lower()}",
        ]
    )

    pipe = subprocess.run(
        commands,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    finished_at = utc_now()
    return dict(
        path=path,
        repo=repo,
        stderr=pipe.stderr,
        stdout=pipe.stdout,
        return_code=pipe.returncode,
        commands=pipe.args,
        started_at=started_at,
        finished_at=finished_at,
        elapsed_seconds=round(time.monotonic() - started_monotonic, 3),
        result_csv=result_csv_path(path),
    )


def build_repo(repo: str, uid: int, gid: int, user: str, data_path: str):
    started_at = utc_now()
    started_monotonic = time.monotonic()
    commands = [
        "docker",
        "build",
        # fmt: off
        f"--build-arg", f"REPO={repo}",
        f"--build-arg", f"BUILD_OS={sys.platform}",
        # fmt: on
    ]
    if sys.platform == "linux":
        commands.extend(
            [
                # fmt: off
                f"--build-arg", f"UID={uid}",
                f"--build-arg", f"GID={gid}",
                f"--build-arg", f"USER={user}",
                # fmt: on
            ]
        )
    else:
        commands.extend(
            [
                # fmt: off
                f"--build-arg", f"USER=root",
                # fmt: on
            ]
        )
    commands.extend(
        [
            f"--build-context",
            f"data={os.path.join(data_path, repo)}",
            f"-t",
            f"typybench-{repo.lower()}",
            f"{os.path.dirname(os.path.realpath(__file__))}",
        ]
    )
    pipe = subprocess.run(
        commands,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    finished_at = utc_now()
    return dict(
        repo=repo,
        stderr=pipe.stderr,
        stdout=pipe.stdout,
        return_code=pipe.returncode,
        commands=pipe.args,
        started_at=started_at,
        finished_at=finished_at,
        elapsed_seconds=round(time.monotonic() - started_monotonic, 3),
    )


def append_progress(path: str | None, payload: dict):
    if path is None:
        return
    progress_path = Path(path)
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    with progress_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")


def write_process_logs(log_dir: str | None, result: dict):
    if log_dir is None:
        return
    repo = result["repo"]
    root = Path(log_dir) / repo
    root.mkdir(parents=True, exist_ok=True)
    (root / "stdout.log").write_bytes(result["stdout"])
    (root / "stderr.log").write_bytes(result["stderr"])
    metadata = {
        "repo": repo,
        "path": result.get("path"),
        "return_code": result["return_code"],
        "commands": result["commands"],
        "started_at": result["started_at"],
        "finished_at": result["finished_at"],
        "elapsed_seconds": result["elapsed_seconds"],
        "result_csv": result.get("result_csv"),
    }
    (root / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def skipped_result(path: str):
    repo = os.path.basename(path)
    return {
        "path": path,
        "repo": repo,
        "stderr": b"",
        "stdout": b"",
        "return_code": 0,
        "commands": [],
        "started_at": utc_now(),
        "finished_at": utc_now(),
        "elapsed_seconds": 0.0,
        "result_csv": result_csv_path(path),
        "skipped": True,
        "skip_reason": "result_csv_exists",
    }


def main(args):
    available_repos = [
        x for x in os.listdir(args.data_path) if is_available_repo(args.data_path, x)
    ]
    if args.repo is not None:
        if args.repo in available_repos:
            available_repos = [args.repo]
        else:
            raise RuntimeError(f"Repo {args.repo} is not found")

    if args.build:
        mapper = functools.partial(build_repo, data_path=args.data_path)
        enabled_repos = available_repos
    else:
        mapper = evaluate_repo
        enabled_repos = []
        for x in os.listdir(args.pred_path):
            if is_available_repo(args.pred_path, x):
                if x in available_repos:
                    enabled_repos.append(os.path.join(args.pred_path, x))
                else:
                    print(f"{x} is not found as a available repo")
        if args.skip_completed:
            remaining_repos = []
            skipped_repos = []
            for path in enabled_repos:
                if has_completed_score(path):
                    skipped_repos.append(path)
                else:
                    remaining_repos.append(path)
            enabled_repos = remaining_repos
            for path in skipped_repos:
                result = skipped_result(path)
                print(f"... Skipping path {path}: result CSV already exists")
                append_progress(
                    args.progress_jsonl,
                    {
                        "event": "repo_skipped",
                        "repo": result["repo"],
                        "path": result["path"],
                        "result_csv": result["result_csv"],
                        "reason": result["skip_reason"],
                        "ts": result["finished_at"],
                    },
                )
    for x in enabled_repos:
        print(f"-> Found an available repo {x} to evaluate")

    append_progress(
        args.progress_jsonl,
        {
            "event": "run_started",
            "build": args.build,
            "num_workers": args.num_workers,
            "enabled_count": len(enabled_repos),
            "data_path": args.data_path,
            "pred_path": args.pred_path,
            "ts": utc_now(),
        },
    )
    mapper = functools.partial(mapper, uid=args.uid, gid=args.gid, user=args.user)
    with multiprocessing.Pool(processes=args.num_workers) as pool:
        key = "repo" if args.build else "path"
        for x in pool.imap_unordered(mapper, enabled_repos):
            write_process_logs(args.log_dir, x)
            append_progress(
                args.progress_jsonl,
                {
                    "event": "repo_finished",
                    "repo": x["repo"],
                    key: x[key],
                    "return_code": x["return_code"],
                    "commands": x["commands"],
                    "started_at": x["started_at"],
                    "finished_at": x["finished_at"],
                    "elapsed_seconds": x["elapsed_seconds"],
                    "result_csv": x.get("result_csv"),
                },
            )
            if x["return_code"]:
                print(f"... Failure on {key} {x[key]}")
                print(f"... commands:\n{x['commands']}\n")
                print(f"... stdout:\n{x['stdout'].decode()}\n")
                print(f"... stderr:\n{x['stderr'].decode()}\n")
            else:
                print(
                    f"... Finished {key} {x[key]} "
                    f"in {x['elapsed_seconds']:.1f}s"
                )
    append_progress(
        args.progress_jsonl,
        {
            "event": "run_finished",
            "build": args.build,
            "enabled_count": len(enabled_repos),
            "ts": utc_now(),
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-path", type=str, required=True, help="path to the typybenchdata folder"
    )
    parser.add_argument(
        "--num-workers",
        type=int,
        default=1,
        help="the number of parallel workers for speeding up evaluation",
    )
    parser.add_argument(
        "--uid", type=int, default=os.geteuid(), help="the current user id"
    )
    parser.add_argument(
        "--gid", type=int, default=os.getegid(), help="the current user group id"
    )
    parser.add_argument(
        "--user", type=str, default=os.getlogin(), help="the current user name"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--build", action="store_true", help="to build the docker image for evaluation"
    )
    group.add_argument(
        "--pred-path",
        type=str,
        help="to evaluate all repos under the given prediction path",
    )
    parser.add_argument(
        "--progress-jsonl",
        type=str,
        default=None,
        help="append machine-readable per-repo progress events to this JSONL file",
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        default=None,
        help="write per-repo stdout/stderr/metadata logs under this directory",
    )
    parser.add_argument(
        "--skip-completed",
        action="store_true",
        help="when scoring, skip repos whose *_results_w_exact.csv already exists",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="specify a single repo to be evaluated (rather than evaluate all repos under the prediction path)",
    )
    main(parser.parse_args())
