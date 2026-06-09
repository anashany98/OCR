import { Card, CardContent } from "@/components/ui/card"

import {
  ActiveFiltersBar,
  ExportBar,
  FilterPanel,
  ModeSelector,
  PageHeader,
  ResultsList,
  SaveSearchBar,
  SavedSearchesCard,
  SearchBreadcrumbs,
  SearchInputBar,
  SearchTipsCard,
} from "./search/components"
import { useSearchPage } from "./search/useSearchPage"

// ---------------------------------------------------------------------------
// F8b-cont5 - search page composition
//
// The previous file was 22 KB / 479 lines mixing seven filter
// fields, the search mode, the search query, the saved-searches
// query, the save-search mutation, the runSearch dispatcher and
// inline sub-components (SearchResultCard, ScoreBadge,
// FilterField).
//
// After F8b-cont5:
// - useSearchPage() owns every piece of state and the two
//   queries (saved-searches + the search itself) plus the
//   save mutation. Returns the raw data + derived flags
//   (activeFilters, filteredResults).
// - Pure helpers extracted and exported: buildActiveFilters,
//   clientFilter, getMatchReason, modeLabel, toSearchMode,
//   runSearch. 16 unit tests cover each one.
// - Components.tsx provides every sub-component as a small
//   testable piece (ModeSelector, SearchInputBar,
//   ActiveFiltersBar, FilterPanel with its FilterSelect and
//   FilterInput helpers, SaveSearchBar, ExportBar,
//   ResultsList, SearchResultCard, ScoreBadge,
//   SavedSearchesCard, SearchTipsCard).
// - The page itself is a thin layout shell: header, two-column
//   grid with the main search area (left) and the sidebar
//   (right).
// ---------------------------------------------------------------------------
export function SearchPage() {
  const s = useSearchPage()
  return (
    <>
      <SearchBreadcrumbs />
      <PageHeader
        title="Buscar"
        description="Encuentra documentos por texto, significado o referencia exacta. Usa filtros para afinar resultados."
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
        <div className="space-y-4">
          <Card>
            <CardContent className="space-y-3 pt-4">
              <ModeSelector mode={s.mode} setMode={s.setMode} />
              <SearchInputBar query={s.query} setQuery={s.setQuery} onSubmit={s.onSubmit} />
              <ActiveFiltersBar
                showFilters={s.showFilters}
                setShowFilters={s.setShowFilters}
                activeFilters={s.activeFilters}
                onClear={s.clearFilters}
                onClearAll={s.clearFilters}
              />
              <FilterPanel
                show={s.showFilters}
                filterType={s.filterType}
                setFilterType={s.setFilterType}
                filterStatus={s.filterStatus}
                setFilterStatus={s.setFilterStatus}
                filterSupplier={s.filterSupplier}
                setFilterSupplier={s.setFilterSupplier}
                filterClient={s.filterClient}
                setFilterClient={s.setFilterClient}
                filterMinConf={s.filterMinConf}
                setFilterMinConf={s.setFilterMinConf}
                filterSourcePath={s.filterSourcePath}
                setFilterSourcePath={s.setFilterSourcePath}
                filterDateFrom={s.filterDateFrom}
                setFilterDateFrom={s.setFilterDateFrom}
                filterDateTo={s.filterDateTo}
                setFilterDateTo={s.setFilterDateTo}
              />
              <SaveSearchBar
                visible={s.submitted.length > 0}
                savedName={s.savedName}
                setSavedName={s.setSavedName}
                onSave={() => s.saveSearch.mutate()}
                isPending={s.saveSearch.isPending}
              />
            </CardContent>
          </Card>

          <ExportBar submitted={s.submitted} query={s.query} />
          <ResultsList
            submitted={s.submitted}
            isLoading={s.results.isLoading}
            results={s.results.data}
            filteredResults={s.filteredResults}
            onAskAbout={s.goToChat}
          />
        </div>

        <div className="space-y-4">
          <SavedSearchesCard
            savedSearches={s.savedSearches.data ?? []}
            onPick={(item) => {
              s.setQuery(item.query)
              s.setSubmitted(item.query)
              s.setMode(item.mode as Parameters<typeof s.setMode>[0])
            }}
          />
          <SearchTipsCard />
        </div>
      </div>
    </>
  )
}
