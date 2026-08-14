# Xiaohongshu Link-Out Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Public Pages no longer host or display Xiaohongshu photos; keep analysis text and original-note links; CI may still send remote image URLs to the model.

**Architecture:** Renderer treats XHS entries as non-displayable images (`_image_url` returns empty). Templates switch those entries to text + outbound links. `cache_photo_assets` is removed. Archives drop `local_url_*`. Historical HTML/Markdown is rebuilt from existing `photos.json` without re-running the LLM.

**Tech Stack:** Python 3.11, Jinja2 templates, unittest, GitHub Pages `output/`.

---

### Task 1: Renderer never emits XHS image URLs

**Files:**
- Create: `tests/test_renderer_xhs_linkout.py`
- Modify: `src/renderer.py`

- [ ] Write failing tests for `_image_url`, `_pick_preview_images`, markdown without `![]`, and `save_archive` stripping `local_url_*`
- [ ] Implement `_is_xhs_entry`, empty `_image_url` for XHS, skip XHS in `_pick_preview_images`, strip local URLs on save
- [ ] Add `rebuild_public_pages(output_dir)` to re-render all days + index + xhs site

### Task 2: Templates become text + link-out

**Files:**
- Modify: `templates/daily.html`, `templates/index.html`, `templates/xhs_index.html`, `templates/xhs_detail.html`

- [ ] Daily XHS cards: no photo frame/lightbox; CTA to original note
- [ ] Homepage XHS picks: no `<img>`; disclaimer; mosaic only if Unsplash previews exist
- [ ] XHS index/detail: no covers/carousel; per-photo analysis as text

### Task 3: Stop downloading assets

**Files:**
- Modify: `src/xhs_fetcher.py`, `src/xhs_daily.py`, `src/xhs_import.py`, `tests/test_xhs_daily.py`, `.gitignore`

- [ ] Delete `cache_photo_assets` and download-only helpers
- [ ] Remove callers; gitignore `output/assets/xhs/`

### Task 4: Rebuild output and docs

**Files:**
- Modify: `output/**`, `docs/PRD.md`, `README.md`, spec status

- [ ] Strip `local_url_*`, rebuild HTML/MD, delete `output/assets/xhs/`
- [ ] Update PRD/README; run unittest
