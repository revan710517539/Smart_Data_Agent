from __future__ import annotations

import re
from functools import lru_cache
from typing import Any


class CaptchaRecognitionError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _ocr_model() -> Any:
    try:
        import ddddocr
    except ImportError as exc:
        raise CaptchaRecognitionError(
            "captcha_ocr_dependency_missing: install the crawler-ocr optional dependency"
        ) from exc
    try:
        return ddddocr.DdddOcr(show_ad=False)
    except TypeError:
        # ddddocr-basic exposes the same classifier without the advertising
        # flag.  Keep compatibility with both the basic and full packages.
        return ddddocr.DdddOcr()


def recognize_digit_captcha(image_bytes: bytes, *, expected_length: int = 4) -> str:
    if not image_bytes:
        raise CaptchaRecognitionError("captcha_image_empty")
    try:
        raw_value = str(_ocr_model().classification(image_bytes) or "")
    except CaptchaRecognitionError:
        raise
    except Exception as exc:
        raise CaptchaRecognitionError("captcha_ocr_failed") from exc
    value = "".join(re.findall(r"\d", raw_value))
    if len(value) != expected_length:
        raise CaptchaRecognitionError(
            f"captcha_ocr_result_invalid:{len(value)}:{expected_length}"
        )
    return value


__all__ = ["CaptchaRecognitionError", "recognize_digit_captcha"]
