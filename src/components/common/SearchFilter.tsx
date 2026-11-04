import React from 'react';
import { Search, X } from 'lucide-react';

interface FilterOption<T extends string = string> {
  value: T;
  label: string;
  count?: number;
}

interface SearchFilterProps<T extends string = string> {
  searchTerm: string;
  onSearchChange: (value: string) => void;
  searchPlaceholder?: string;
  filterValue?: T;
  onFilterChange?: (value: T) => void;
  filterOptions?: FilterOption<T>[];
}

export function SearchFilter<T extends string = string>({
  searchTerm,
  onSearchChange,
  searchPlaceholder = 'Search records…',
  filterValue,
  onFilterChange,
  filterOptions,
}: SearchFilterProps<T>) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-5">
      {/* Search Input */}
      <div className="relative flex-1 max-w-md">
        <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-slate-400 pointer-events-none">
          <Search size={15} />
        </span>
        <input
          type="text"
          value={searchTerm}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder={searchPlaceholder}
          className="w-full pl-9 pr-8 py-2 text-xs sm:text-sm bg-white border border-slate-200 rounded-lg focus:outline-hidden focus:ring-1 focus:ring-emerald-700 focus:border-emerald-700 shadow-2xs font-normal"
        />
        {searchTerm && (
          <button
            onClick={() => onSearchChange('')}
            className="absolute inset-y-0 right-0 pr-2.5 flex items-center text-slate-400 hover:text-slate-600"
          >
            <X size={14} />
          </button>
        )}
      </div>

      {/* Segmented Filter Control */}
      {filterOptions && filterOptions.length > 0 && onFilterChange && (
        <div className="flex items-center gap-1 p-1 bg-slate-100 rounded-lg overflow-x-auto shrink-0 border border-slate-200/60">
          {filterOptions.map((opt) => {
            const isActive = filterValue === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => onFilterChange(opt.value)}
                className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-all cursor-pointer whitespace-nowrap flex items-center gap-1.5 ${
                  isActive
                    ? 'bg-white text-slate-900 shadow-xs'
                    : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                <span>{opt.label}</span>
                {opt.count !== undefined && (
                  <span
                    className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold ${
                      isActive
                        ? 'bg-emerald-100 text-emerald-800'
                        : 'bg-slate-200 text-slate-600'
                    }`}
                  >
                    {opt.count}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
