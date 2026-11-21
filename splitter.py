"""PDF 분할 엔진.

- pikepdf(qpdf 기반, 빠르고 메모리 적게 씀)가 있으면 그걸 쓰고,
  없거나 실패하면 pypdf 로 대신 처리한다.
- 세 가지 방식: 지정한 페이지에서 자르기 / N쪽씩 / N MB 이하로 자동.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

try:
    import pikepdf  # type: ignore
except Exception:  # pragma: no cover
    pikepdf = None

try:
    from pypdf import PdfReader, PdfWriter  # type: ignore
except Exception:  # pragma: no cover
    PdfReader = PdfWriter = None


class SplitError(Exception):
    pass


class Cancelled(Exception):
    pass


Range = Tuple[int, int]  # 1부터 시작, 양끝 포함 (start, end)


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


# ---------------------------------------------------------------- 입력 해석
def parse_page_spec(text: str, total: int) -> List[Range]:
    """사용자 입력을 페이지 구간 목록으로 바꾼다.

    - "100, 250"           → 100쪽 뒤, 250쪽 뒤에서 자름: 1-100, 101-250, 251-끝
    - "1-100, 150-200"     → 적은 구간만 그대로 뽑음
    - 섞어 쓰기도 가능: "1-50, 120" → 1-50, 51-120, 121-끝 처럼 해석하지 않고
      '-' 가 하나라도 있으면 구간 모드로 보고, 숫자 하나는 그 한 쪽만 뽑는다.
    """
    text = text.strip()
    if not text:
        raise SplitError("자를 페이지를 입력해 주세요. 예) 100, 250")
    tokens = [t.strip() for t in re.split(r"[,\s]+", text) if t.strip()]
    tokens = [t.replace("~", "-").replace("–", "-") for t in tokens]

    if any("-" in t for t in tokens):
        ranges: List[Range] = []
        for t in tokens:
            m = re.fullmatch(r"(\d+)?-(\d+)?|(\d+)", t)
            if not m:
                raise SplitError(f"'{t}' 를 이해하지 못했어요. 예) 1-100, 101-250")
            if m.group(3):
                a = b = int(m.group(3))
            else:
                a = int(m.group(1)) if m.group(1) else 1
                b = int(m.group(2)) if m.group(2) else total
            if a < 1 or b > total or a > b:
                raise SplitError(f"'{t}' 는 범위를 벗어나요 (1~{total}쪽).")
            ranges.append((a, b))
        return ranges

    cuts = []
    for t in tokens:
        if not t.isdigit():
            raise SplitError(f"'{t}' 는 숫자가 아니에요.")
        c = int(t)
        if c < 1 or c >= total:
            raise SplitError(f"{c}쪽 뒤에서는 자를 수 없어요 (1~{total - 1} 사이로).")
        cuts.append(c)
    cuts = sorted(set(cuts))
    ranges = []
    start = 1
    for c in cuts:
        ranges.append((start, c))
        start = c + 1
    ranges.append((start, total))
    return ranges


def ranges_every(n: int, total: int) -> List[Range]:
    if n < 1:
        raise SplitError("1쪽 이상으로 입력해 주세요.")
    return [(a, min(a + n - 1, total)) for a in range(1, total + 1, n)]


def ranges_into(k: int, total: int) -> List[Range]:
    if k < 1:
        raise SplitError("1개 이상으로 입력해 주세요.")
    k = min(k, total)
    base, extra = divmod(total, k)
    out, a = [], 1
    for i in range(k):
        size = base + (1 if i < extra else 0)
        out.append((a, a + size - 1))
        a += size
    return out


def estimate_ranges_by_size(limit_bytes: int, total: int, file_size: int) -> List[Range]:
    """미리보기용 대략적 계획 (페이지 용량이 고르다고 가정)."""
    per_page = max(1.0, file_size / max(1, total))
    n = max(1, int(limit_bytes * 0.9 / per_page))
    return ranges_every(n, total)


# ---------------------------------------------------------------- 문서 열기
@dataclass
class PdfInfo:
    path: str
    pages: int
    size: int
    engine: str


class PdfSource:
    """원본 PDF 를 한 번만 열어 두고 여러 조각을 써 낸다."""

    def __init__(self, path: str):
        self.path = path
        self.size = os.path.getsize(path)
        self._pk = None
        self._rd = None
        self.engine = ""
        errors = []
        if pikepdf is not None:
            try:
                self._pk = pikepdf.open(path)
                self.pages = len(self._pk.pages)
                self.engine = "pikepdf"
                return
            except Exception as e:  # 암호 등
                errors.append(f"pikepdf: {e}")
                self._pk = None
        if PdfReader is not None:
            try:
                rd = PdfReader(path)
                if rd.is_encrypted:
                    try:
                        ok = rd.decrypt("")
                    except Exception:
                        ok = 0
                    if not ok:
                        raise SplitError("암호가 걸린 PDF 라서 열 수 없어요.")
                self._rd = rd
                self.pages = len(rd.pages)
                self.engine = "pypdf"
                return
            except SplitError:
                raise
            except Exception as e:
                errors.append(f"pypdf: {e}")
        if not errors:
            raise SplitError("PDF 라이브러리가 없어요. 1_install.bat 를 먼저 실행해 주세요.")
        raise SplitError("PDF 를 열지 못했어요.\n" + "\n".join(errors))

    @property
    def info(self) -> PdfInfo:
        return PdfInfo(self.path, self.pages, self.size, self.engine)

    def close(self):
        try:
            if self._pk is not None:
                self._pk.close()
        except Exception:
            pass
        self._pk = None
        self._rd = None

    # 조각 하나 쓰기 (start, end 는 1부터, 양끝 포함)
    def write_part(self, start: int, end: int, out_path: str) -> int:
        tmp = out_path + ".tmp"
        try:
            if self._pk is not None:
                try:
                    self._write_pikepdf(start, end, tmp)
                except Exception:
                    if PdfReader is None:
                        raise
                    if self._rd is None:
                        self._rd = PdfReader(self.path)
                        if self._rd.is_encrypted:
                            self._rd.decrypt("")
                    self._write_pypdf(start, end, tmp)
            else:
                self._write_pypdf(start, end, tmp)
            os.replace(tmp, out_path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        return os.path.getsize(out_path)

    def _write_pikepdf(self, start, end, path):
        out = pikepdf.Pdf.new()
        try:
            out.pages.extend(self._pk.pages[start - 1:end])
            out.save(path)
        finally:
            out.close()

    def _write_pypdf(self, start, end, path):
        w = PdfWriter()
        for i in range(start - 1, end):
            w.add_page(self._rd.pages[i])
        try:
            w.compress_identical_objects(remove_identicals=True, remove_orphans=True)
        except Exception:
            pass
        with open(path, "wb") as f:
            w.write(f)


# ---------------------------------------------------------------- 실행
ProgressFn = Callable[[float, str], None]


def part_name(stem: str, idx: int, start: int, end: int, digits: int = 2) -> str:
    pages = f"p{start}" if start == end else f"p{start}-{end}"
    return f"{stem}_{idx:0{digits}d}_{pages}.pdf"


def split_ranges(src: PdfSource, ranges: List[Range], out_dir: str, stem: str,
                 progress: Optional[ProgressFn] = None,
                 cancel: Optional[Callable[[], bool]] = None) -> List[Tuple[str, int, int, int]]:
    os.makedirs(out_dir, exist_ok=True)
    total_pages = sum(b - a + 1 for a, b in ranges) or 1
    done_pages = 0
    digits = max(2, len(str(len(ranges))))
    results = []
    for i, (a, b) in enumerate(ranges, 1):
        if cancel and cancel():
            raise Cancelled()
        if progress:
            progress(done_pages / total_pages, f"{i}/{len(ranges)} 번째 조각 만드는 중  ({a}~{b}쪽)")
        path = os.path.join(out_dir, part_name(stem, i, a, b, digits))
        size = src.write_part(a, b, path)
        results.append((path, a, b, size))
        done_pages += b - a + 1
    if progress:
        progress(1.0, "완료!")
    return results


def split_by_size(src: PdfSource, limit_bytes: int, out_dir: str, stem: str,
                  progress: Optional[ProgressFn] = None,
                  cancel: Optional[Callable[[], bool]] = None) -> List[Tuple[str, int, int, int]]:
    """각 조각이 limit_bytes 이하가 되도록 실제로 써 보면서 크기를 맞춘다."""
    if limit_bytes < 1024 * 100:
        raise SplitError("용량 제한이 너무 작아요 (0.1 MB 이상).")
    os.makedirs(out_dir, exist_ok=True)
    total = src.pages
    per_page = max(1.0, src.size / total)
    results = []
    pos = 1
    idx = 0
    work = os.path.join(out_dir, f".{stem}_work.pdf")
    best = os.path.join(out_dir, f".{stem}_best.pdf")
    try:
        while pos <= total:
            if cancel and cancel():
                raise Cancelled()
            idx += 1
            guess = max(1, int(limit_bytes * 0.92 / per_page))
            end = min(total, pos + guess - 1)
            ok_end, ok_size = None, None   # 제한 안에 들어온 가장 긴 끝 페이지
            bad_end = None                 # 제한을 넘은 가장 짧은 끝 페이지
            oversized_single = False
            for _ in range(12):
                if cancel and cancel():
                    raise Cancelled()
                if progress:
                    progress((pos - 1) / total,
                             f"{idx}번째 조각 크기 맞추는 중  ({pos}~{end}쪽 시도)")
                size = src.write_part(pos, end, work)
                if size <= limit_bytes:
                    ok_end, ok_size = end, size
                    os.replace(work, best)
                    if end == total or size >= limit_bytes * 0.85:
                        break
                    if bad_end is not None and bad_end - end <= 1:
                        break
                    n = end - pos + 1
                    new_end = pos + int(n * limit_bytes * 0.95 / max(size, 1)) - 1
                    new_end = max(new_end, end + 1)
                    if bad_end is not None:
                        new_end = min(new_end, bad_end - 1)
                    new_end = min(new_end, total)
                    if new_end <= end:
                        break
                    end = new_end
                else:
                    bad_end = end
                    if end == pos:  # 한 쪽만으로도 제한 초과
                        ok_end, ok_size = end, size
                        os.replace(work, best)
                        oversized_single = True
                        break
                    n = end - pos + 1
                    new_end = pos + int(n * limit_bytes * 0.92 / size) - 1
                    new_end = min(new_end, end - 1)
                    if ok_end is not None and new_end <= ok_end:
                        if ok_end + 1 < bad_end:
                            new_end = ok_end + 1   # 한 쪽만 더 넣어 보기
                        else:
                            break  # 이미 들어간 길이가 최선
                    new_end = max(new_end, pos)
                    end = new_end
            if ok_end is None:
                raise SplitError("조각 크기를 맞추지 못했어요.")
            final = os.path.join(out_dir, part_name(stem, idx, pos, ok_end, 3))
            os.replace(best, final)
            results.append((final, pos, ok_end, ok_size))
            if oversized_single and progress:
                progress((ok_end) / total, f"⚠ {pos}쪽 한 장이 제한보다 커서 그대로 저장했어요")
            n = ok_end - pos + 1
            per_page = max(1.0, ok_size / n)
            pos = ok_end + 1
    finally:
        for p in (work, best):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
    # 이름의 자릿수 정리 (001 → 01)
    digits = max(2, len(str(len(results))))
    tidy = []
    for i, (p, a, b, s) in enumerate(results, 1):
        newp = os.path.join(out_dir, part_name(stem, i, a, b, digits))
        if newp != p:
            os.replace(p, newp)
        tidy.append((newp, a, b, s))
    if progress:
        progress(1.0, "완료!")
    return tidy
