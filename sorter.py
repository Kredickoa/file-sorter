"""Sort the files directly inside a folder after previewing the changes."""

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys


CATEGORIES = {
    "Photos": {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".avif", ".svg"},
    "Videos": {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".mpg", ".mpeg"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt", ".csv", ".xls", ".xlsx", ".ods", ".ppt", ".pptx", ".epub"},
    "Music": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz"},
}


@dataclass(frozen=True)
class Move:
    """One reviewed source file and its planned destination."""

    source: Path
    destination: Path


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def plan_moves(folder: Path) -> tuple[list[Move], list[str]]:
    """Plan top-level moves without creating folders or changing any files."""
    if not folder.is_dir():
        raise ValueError(f"Not a folder: {folder}")
    moves = []
    errors = []
    reserved = {}
    for source in sorted(folder.iterdir(), key=lambda path: (path.name.casefold(), path.name)):
        try:
            if source.name.startswith(".") or _is_link(source) or not source.is_file():
                continue
            if source.resolve() == Path(__file__).resolve():
                continue
            category = next((name for name, extensions in CATEGORIES.items()
                             if source.suffix.lower() in extensions), "Other")
            destination_folder = folder / category
            if _is_link(destination_folder):
                raise OSError(f"{category} is a link; left the file in place")
            if destination_folder.exists() and not destination_folder.is_dir():
                raise OSError(f"{category} exists but is not a folder")
            if category not in reserved:
                reserved[category] = ({path.name.casefold() for path in destination_folder.iterdir()}
                                      if destination_folder.exists() else set())
            name = source.name
            number = 1
            while name.casefold() in reserved[category]:
                name = f"{source.stem}_{number}{source.suffix}"
                number += 1
            reserved[category].add(name.casefold())
            moves.append(Move(source, destination_folder / name))
        except OSError as error:
            errors.append(f"{source.name}: {error}")
    return moves, errors


def _move_without_overwrite(source: Path, destination: Path) -> None:
    created = False
    try:
        with source.open("rb") as incoming:
            before = os.fstat(incoming.fileno())
            with destination.open("xb") as outgoing:
                created = True
                shutil.copyfileobj(incoming, outgoing)
                outgoing.flush()
                os.fsync(outgoing.fileno())
        after = source.stat(follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in fields):
            raise OSError("File changed while copying; original left in place")
        os.utime(destination, ns=(before.st_atime_ns, before.st_mtime_ns))
        source.unlink()
    except OSError:
        if created:
            try:
                destination.unlink()
            except OSError:
                pass
        raise


def apply_moves(moves: list[Move]) -> tuple[int, list[str]]:
    """Apply a plan, preserving existing files and reporting individual failures."""
    moved = 0
    errors = []
    for move in moves:
        try:
            if _is_link(move.source) or not move.source.is_file():
                raise OSError("Source is no longer a regular file")
            if _is_link(move.destination.parent):
                raise OSError("Destination is a link")
            move.destination.parent.mkdir(exist_ok=True)
            _move_without_overwrite(move.source, move.destination)
            moved += 1
        except OSError as error:
            errors.append(f"{move.source.name}: {error}")
    return moved, errors


def main(argv: list[str] | None = None) -> int:
    """Run the preview, optional confirmation and sorting command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="?", type=Path, help="Folder to organise; subfolders are left alone")
    parser.add_argument("--dry-run", action="store_true", help="Show the plan without moving anything")
    parser.add_argument("--yes", action="store_true", help="Confirm the displayed plan automatically")
    args = parser.parse_args(argv)
    if args.folder is None:
        print("\nFile Sorter\n")
        try:
            entered = input("Folder to sort: ").strip().strip('"')
        except EOFError:
            print("Cancelled. No files were moved.")
            return 0
        if not entered:
            print("Error: Enter a folder path.", file=sys.stderr)
            return 1
        args.folder = Path(entered)
    try:
        folder = args.folder.expanduser().resolve(strict=True)
        moves, errors = plan_moves(folder)
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"\nFile Sorter | {folder}\n")
    for move in moves:
        print(f"  {move.source.name} -> {move.destination.parent.name}/{move.destination.name}")
    for error in errors:
        print(f"Skipped: {error}", file=sys.stderr)
    print(f"\n{len(moves)} file(s) ready to sort.")
    if args.dry_run or not moves:
        return int(bool(errors))
    if not args.yes:
        try:
            answer = input("Move these files? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in {"y", "yes"}:
            print("Cancelled. No files were moved.")
            return int(bool(errors))

    moved, failures = apply_moves(moves)
    for error in failures:
        print(f"Could not move: {error}", file=sys.stderr)
    print(f"Done: {moved} moved, {len(errors) + len(failures)} failed or skipped.")
    return int(bool(errors or failures))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped. Already completed moves are kept.", file=sys.stderr)
        raise SystemExit(130)
