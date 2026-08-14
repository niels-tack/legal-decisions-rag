/**
 * Every user-facing UI string, in one place. The POC ships Dutch-only (see
 * the functional requirements - corpus and UI are Dutch for now), but
 * centralizing here means adding French/English later is a translation
 * file, not a hunt-and-replace across components.
 */
export const strings = {
  pageTitle: "Zoek in uitspraken van het Grondwettelijk Hof",
  heading: "Zoek in Belgische rechterlijke uitspraken",
  privacyNote:
    "🔒 Uw zoekopdracht verlaat nooit uw browser: het zoeken gebeurt volledig lokaal, er wordt niets naar een server verzonden.",
  searchPlaceholder: 'Zoekterm, arrestnummer of ECLI, bv. "omgevingsvergunning"',
  searchButton: "Zoeken",
  queryGuidance:
    "Dit is een trefwoordenzoeker (geen natuurlijke taal): gebruik juridische terminologie, een arrestnummer, of een ECLI voor de beste resultaten.",
  exampleQueriesLabel: "Voorbeelden:",

  filtersLegend: "Filters",
  filterDateFrom: "Vanaf datum",
  filterDateTo: "Tot datum",
  filterProcedureType: "Procedure type",
  filterSource: "Rechtscollege",
  filterAllOption: "Alle",
  sortLabel: "Sorteren op",
  sortByRelevance: "Relevantie",
  sortByDateNewest: "Datum (nieuw – oud)",
  sortByDateOldest: "Datum (oud – nieuw)",

  statusLoadingIndex: "Zoekindex laden…",
  statusLoadIndexFailed: "Kon de zoekindex niet laden. Herlaad de pagina om opnieuw te proberen.",
  statusSearching: "Zoeken…",
  statusSearchFailed: "Er ging iets mis bij het zoeken. Probeer het opnieuw.",
  statusNoResults:
    "Geen resultaten gevonden. Probeer een juridische term, een arrestnummer, of pas de filters aan.",
  statusResultsCount: (count: number): string =>
    count === 1 ? "1 resultaat gevonden." : `${count} resultaten gevonden.`,

  paginationPrevious: "Vorige",
  paginationNext: "Volgende",
  paginationPageOf: (page: number, totalPages: number): string =>
    `Pagina ${page} van ${totalPages}`,

  resultSelectLabel: "Opnemen in prompt",
  resultOpenCase: "Volledige uitspraak",
  resultOpenPdf: "Origineel PDF",

  handoffCopyButton: "📋 Kopieer prompt voor AI-assistent",
  handoffCopySuccess: "Gekopieerd! Plak dit in Copilot, ChatGPT of Claude.",
  handoffCopyFailure: "Kopiëren mislukt – selecteer en kopieer handmatig.",
  handoffNoneSelected: "Selecteer minstens één resultaat om een prompt samen te stellen.",

  footerSourceAttribution: "Bron: officiële uitspraken van het Grondwettelijk Hof.",
  footerDisclaimer: "Dit is geen juridisch advies. Verifieer elke uitspraak aan de hand van het originele PDF.",
  footerBuiltAtPrefix: "Laatst bijgewerkt:",

  readerBackToSearch: "← Terug naar zoeken",
} as const;
