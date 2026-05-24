#!/usr/bin/env python3
"""
Unit tests for hpprgm2ppl (decompiler) and ppl2hpprgm (compiler).

Reference data:
  samples/export/geometry.hpprgm  – real file exported from HP Prime via HP Connectivity Kit
  samples/export/aviation.hpprgm  – real file exported from HP Prime via HP Connectivity Kit
  samples/src/triVA.ppl           – source copy-pasted from HP Connectivity Kit editor
  samples/src/triS.ppl            – same
  samples/src/NavFuel.ppl .. NavWind.ppl  – aviation source files (no #pragma)
  samples/src/geometry.json       – project definition file (geometry)
  samples/src/aviation.json       – project definition file (aviation)

Convention: .ppl source files may optionally contain a #pragma directive.
The compiler stores source text as-is in the binary – no pragma is added or
removed.  HP Prime reference exports may or may not contain pragma depending on
how the program was originally entered.

_norm_src() is used when comparing against reference exports of unknown pragma
status; _norm() is used for pure compile/decompile round-trips where both sides
come from the same .ppl sources (no pragma injected).
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from hpprgm2ppl import extract_programs, decompile, write_project_file
from ppl2hpprgm import compile_ppl, load_project

SAMPLES           = Path(__file__).parent / 'samples'
EXPORT_DIR        = SAMPLES / 'export'
SRC_DIR           = SAMPLES / 'src'
HPPRGM            = EXPORT_DIR / 'geometry.hpprgm'
AVIATION_HPPRGM   = EXPORT_DIR / 'aviation.hpprgm'
AVIATION_PROGRAMS = ['NavFuel', 'NavTas', 'NavTopD', 'NavWca', 'NavWind']


def _norm(text: str) -> str:
    """Normalize line endings, strip surrounding whitespace."""
    return text.replace('\r\n', '\n').replace('\r', '\n').strip()


def _norm_src(text: str) -> str:
    """Like _norm but also strips #pragma lines.

    Used when comparing decompiler output from a binary that predates the
    pragma convention (e.g. geometry.hpprgm exported directly from HP Prime).
    """
    lines = text.replace('\r\n', '\n').replace('\r', '\n').splitlines()
    return '\n'.join(l for l in lines if not l.strip().startswith('#pragma')).strip()


class TestDecompile(unittest.TestCase):
    """Decompile geometry.hpprgm and compare with reference .ppl files."""

    @classmethod
    def setUpClass(cls):
        cls.programs = dict(extract_programs(HPPRGM.read_bytes()))

    def test_program_count(self):
        self.assertEqual(len(self.programs), 2)

    def test_program_names(self):
        self.assertIn('triVA', self.programs)
        self.assertIn('triS',  self.programs)

    def test_triVA_matches_reference(self):
        # geometry.hpprgm was exported from HP Prime without #pragma; compare body only
        expected = _norm_src((SRC_DIR / 'triVA.ppl').read_text(encoding='utf-8'))
        actual   = _norm_src(self.programs['triVA'])
        self.assertEqual(actual, expected)

    def test_triS_matches_reference(self):
        expected = _norm_src((SRC_DIR / 'triS.ppl').read_text(encoding='utf-8'))
        actual   = _norm_src(self.programs['triS'])
        self.assertEqual(actual, expected)


class TestProjectFile(unittest.TestCase):
    """Project definition file: generation by decompiler and consumption by compiler."""

    def test_decompile_generates_project_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            decompile(HPPRGM, Path(tmp))
            self.assertTrue((Path(tmp) / 'geometry.json').exists())

    def test_generated_project_matches_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            decompile(HPPRGM, Path(tmp))
            generated = json.loads((Path(tmp) / 'geometry.json').read_text(encoding='utf-8'))
            reference = json.loads((SRC_DIR / 'geometry.json').read_text(encoding='utf-8'))
            self.assertEqual(generated, reference)

    def test_project_output_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            decompile(HPPRGM, Path(tmp))
            project = json.loads((Path(tmp) / 'geometry.json').read_text(encoding='utf-8'))
            self.assertEqual(project['output'], 'geometry.hpprgm')

    def test_project_programs_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            decompile(HPPRGM, Path(tmp))
            project = json.loads((Path(tmp) / 'geometry.json').read_text(encoding='utf-8'))
            self.assertEqual(project['programs'], ['triVA.ppl', 'triS.ppl'])

    def test_load_project_returns_correct_output(self):
        output, _ = load_project(SRC_DIR / 'geometry.json')
        self.assertEqual(output.name, 'geometry.hpprgm')

    def test_load_project_returns_correct_sources(self):
        _, sources = load_project(SRC_DIR / 'geometry.json')
        self.assertEqual([s.name for s in sources], ['triVA.ppl', 'triS.ppl'])

    def test_compile_from_project_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for f in SRC_DIR.iterdir():
                if f.is_file():          # skip sub-directories (e.g. build/)
                    shutil.copy(f, tmp_path)

            output, sources = load_project(tmp_path / 'geometry.json')
            compile_ppl(sources, output)

            self.assertTrue(output.exists())
            programs = dict(extract_programs(output.read_bytes()))
            self.assertIn('triVA', programs)
            self.assertIn('triS',  programs)


class TestCompileRoundtrip(unittest.TestCase):
    """Compile src/*.ppl → .hpprgm, decompile back, compare with originals."""

    def test_roundtrip_all_sources(self):
        sources = sorted(SRC_DIR.glob('*.ppl'))
        self.assertTrue(sources, f'No .ppl files found in {SRC_DIR}')

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'test.hpprgm'
            compile_ppl(sources, output)

            self.assertTrue(output.exists(), 'Compiler produced no output file')
            self.assertGreater(output.stat().st_size, 64, 'Output file suspiciously small')

            programs = dict(extract_programs(output.read_bytes()))

            for src in sources:
                with self.subTest(program=src.stem):
                    expected = _norm(src.read_text(encoding='utf-8'))
                    actual   = _norm(programs.get(src.stem, ''))
                    self.assertEqual(actual, expected)

    def test_roundtrip_via_project_file(self):
        """Full round-trip: decompile → project file → compile → decompile → compare."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Step 1: decompile into tmp, generating .ppl files and project file
            decompile(HPPRGM, tmp_path)

            # Step 2: compile using the generated project file
            output, sources = load_project(tmp_path / 'geometry.json')
            compile_ppl(sources, output)

            # Step 3: decompile the recompiled binary
            programs = dict(extract_programs(output.read_bytes()))

            # Step 4: compare against original reference sources.
            for name in ('triVA', 'triS'):
                with self.subTest(program=name):
                    expected = _norm((SRC_DIR / f'{name}.ppl').read_text(encoding='utf-8'))
                    actual   = _norm(programs.get(name, ''))
                    self.assertEqual(actual, expected)

    def test_roundtrip_preserves_unicode(self):
        """Special chars (≤, √, Czech) must survive UTF-16-LE encode/decode."""
        sources  = sorted(SRC_DIR.glob('*.ppl'))
        combined = ''.join(s.read_text(encoding='utf-8') for s in sources)
        self.assertIn('≤', combined, 'Test file missing ≤ – update sample')
        self.assertIn('√', combined, 'Test file missing √ – update sample')

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'unicode.hpprgm'
            compile_ppl(sources, output)
            programs = dict(extract_programs(output.read_bytes()))

        for src in sources:
            original  = src.read_text(encoding='utf-8')
            recovered = programs.get(src.stem, '')
            for ch in '≤√':
                if ch in original:
                    self.assertIn(ch, recovered,
                                  f'{ch!r} lost in round-trip for {src.stem}')


class TestAviationDecompile(unittest.TestCase):
    """
    Decompile the reference aviation.hpprgm (exported from HP Prime) and
    verify the extracted source matches the sample .ppl files.

    The reference binary was produced on the HP Prime with #pragma in each
    program, so _norm_src() strips it before comparing with .ppl files
    that carry no pragma by convention.
    """

    @classmethod
    def setUpClass(cls):
        cls.programs = dict(extract_programs(AVIATION_HPPRGM.read_bytes()))

    def test_program_count(self):
        self.assertEqual(len(self.programs), len(AVIATION_PROGRAMS))

    def test_program_names(self):
        for name in AVIATION_PROGRAMS:
            self.assertIn(name, self.programs)

    def test_sources_match_reference_ppl(self):
        """Each decompiled program must match the corresponding .ppl file."""
        for name in AVIATION_PROGRAMS:
            with self.subTest(program=name):
                expected = _norm_src((SRC_DIR / f'{name}.ppl').read_text(encoding='utf-8'))
                actual   = _norm_src(self.programs[name])
                self.assertEqual(actual, expected)


class TestAviationCompile(unittest.TestCase):
    """
    Compile the aviation .ppl files and verify the resulting binary is valid:
    all five programs must be recoverable with the correct source content.
    """

    def _compiled_programs(self) -> dict:
        """Compile aviation sources in a temp dir and return extracted programs."""
        sources = [SRC_DIR / f'{name}.ppl' for name in AVIATION_PROGRAMS]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'aviation.hpprgm'
            compile_ppl(sources, output)
            return dict(extract_programs(output.read_bytes()))

    def test_compile_produces_all_programs(self):
        programs = self._compiled_programs()
        for name in AVIATION_PROGRAMS:
            self.assertIn(name, programs)

    def test_compiled_sources_survive_roundtrip(self):
        """Source content must be preserved through compile → decompile."""
        programs = self._compiled_programs()
        for name in AVIATION_PROGRAMS:
            with self.subTest(program=name):
                expected = _norm((SRC_DIR / f'{name}.ppl').read_text(encoding='utf-8'))
                actual   = _norm(programs.get(name, ''))
                self.assertEqual(actual, expected)

    def test_compile_from_project_file(self):
        """Full path: load aviation.json, compile, verify all programs present."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for f in SRC_DIR.iterdir():
                if f.is_file():
                    shutil.copy(f, tmp_path)

            output, sources = load_project(tmp_path / 'aviation.json')
            compile_ppl(sources, output)

            self.assertTrue(output.exists())
            programs = dict(extract_programs(output.read_bytes()))
            for name in AVIATION_PROGRAMS:
                self.assertIn(name, programs)


if __name__ == '__main__':
    unittest.main(verbosity=2)
