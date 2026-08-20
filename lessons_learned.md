# Lessons learned

## Corpus audit

The Dutch Constitutional Court sample was expanded with 141 rulings from
2000. Together with the existing 92 rulings from 2026, the sister repository
now contains 233 Markdown cases. A deterministic audit of the 2000 files
found:

- 141 valid Markdown files with parseable YAML frontmatter.
- 141 explicit `ecli: null` values. Missing ECLI is normal for this older
  corpus and must not block ingestion.
- No filename, slug, case-number, or PDF-URL identity mismatches.
- No missing required identity or source-location fields.
- Sections are present in every file.
- 3,866 anchored `A.*` and `B.*` paragraph markers.

The index and static-site builders also process the combined 233-case corpus
successfully. The resulting index contains 233 cases and 10,319 chunks.

## Identity rules

The PDF filename, official case number, and ECLI are related identifiers, not
interchangeable fields. The filename and case number are reliable for the
2000 sample, but ECLI may be absent or may refer to a different publication
sequence in other years.

The ingestion pipeline therefore keeps the identifiers separate. Missing ECLI
is stored as `null`. When an ECLI is present, its year and sequence are checked
against the filename and case number. A mismatch produces a warning but does
not discard the ruling, because delayed publication and renumbering are valid
possibilities.

## Metadata completeness

Descriptive metadata can be absent in source material. Docket number, ruling
date, procedure type, controlled norm, outcome, and ECLI are nullable. Empty
keyword lists are represented as `[]`. Source, case number, file slug, and
official PDF URL remain required because they are needed to identify and verify
the ruling.

Missing values must remain distinguishable from real values. In particular,
`date.min` is not a suitable substitute for an unknown ruling date because it
can corrupt sorting and date filtering.

## Paragraph markers

Most Constitutional Court paragraph markers use a trailing period, for example
`B.7.3.`. A small number of 2000 rulings omit that period, for example
`B.3.1 In ...`. The marker expression accepts this form when it is followed by
an uppercase sentence start.

Line-start references such as `B.6.2 en B.6.3.` are not paragraph starts. A
marker regex must therefore be anchored to the line and must avoid treating
lowercase continuation text as a new paragraph. Marker parsing remains a
heuristic at this boundary; future corpus audits should report new shapes
before publication.

## Operational lessons

- Validate the full corpus, not only a handful of recent rulings.
- Keep derived titles focused on the substantive norm; procedure type remains
  a separate metadata field for filtering and display.
- Keep network discovery, PDF extraction, metadata assembly, indexing, and
  static rendering independently testable.
- Treat warnings as data-quality signals while allowing recoverable cases to
  continue through ingestion.
- Rebuild the SQLite index and static pages from the same Markdown input, then
  compare their case counts before publishing.