import { createTheme, type CSSVariablesResolver, type MantineColorsTuple } from '@mantine/core';

// Single source of the design's colours (Aura Build: Figma + Central de Controle HTML).
// Components read them as Mantine colours (`c="maravi"`) or as CSS variables
// (`var(--mantine-color-navy-9)`, `var(--app-…)`); no hex value lives outside this file.

// Primary blue: shade 6 is #126DAD, shade 7 its hover #105F96.
const maravi: MantineColorsTuple = [
  '#eaf2f8',
  '#d4e5f1',
  '#a7cbe4',
  '#78b0d7',
  '#4f97cb',
  '#2f86c2',
  '#126dad',
  '#105f96',
  '#0d5180',
  '#0a426a',
];

// Sidebar navy: shade 9 is the background (#102B46), shade 6 the active item (#24516D),
// shade 2 the idle link text (#B0C1D0).
const navy: MantineColorsTuple = [
  '#e8eef4',
  '#cfdbe6',
  '#b0c1d0',
  '#7f9ab2',
  '#557894',
  '#3a6380',
  '#24516d',
  '#1b415b',
  '#153650',
  '#102b46',
];

const other = {
  pageBackground: '#F8FAFC',
  border: '#E2E8F0',
  textMuted: '#64748B',
  accent: '#29B8D0',
  sidebarMuted: '#94A3B8',
  sidebarHover: 'rgb(255 255 255 / 5%)',
  sidebarDivider: 'rgb(255 255 255 / 10%)',
};

export const theme = createTheme({
  primaryColor: 'maravi',
  primaryShade: 6,
  colors: { maravi, navy },
  black: '#0F172A',
  fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
  headings: { fontWeight: '500' },
  defaultRadius: 'md',
  other,
  components: {
    Paper: { defaultProps: { withBorder: true, radius: 'md' } },
    Card: { defaultProps: { withBorder: true, radius: 'md' } },
    Tooltip: { defaultProps: { withArrow: true } },
    // Menus and date pickers open from table rows and fields: keep them open while in use,
    // even when the row or field scrolls out of view (Floating UI's "hide" would close them).
    Popover: { defaultProps: { hideDetached: false } },
  },
});

/** Exposes `theme.other` as `--app-*` CSS variables and sets the page background. */
export const cssVariablesResolver: CSSVariablesResolver = () => {
  const variables = {
    '--app-page-bg': other.pageBackground,
    '--app-border': other.border,
    '--app-text-muted': other.textMuted,
    '--app-accent': other.accent,
    '--app-sidebar-muted': other.sidebarMuted,
    '--app-sidebar-hover': other.sidebarHover,
    '--app-sidebar-divider': other.sidebarDivider,
  };
  return {
    variables,
    light: { '--mantine-color-body': other.pageBackground },
    dark: {},
  };
};
