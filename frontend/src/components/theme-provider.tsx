import { ThemeProvider as NextThemesProvider, useTheme } from 'next-themes'
import { useEffect, type ReactNode } from 'react'

/** The estate's four themes, in the order a picker should offer them. */
export const THEMES = ['warm', 'green', 'mono', 'paper'] as const
export type Theme = (typeof THEMES)[number]

/** The two that are near-black. Everything else is a light surface. */
const DARK_THEMES = new Set<string>(['green', 'mono'])

/**
 * Keeps Tailwind's `.dark` class in step with the chosen theme.
 *
 * The palette moved to `html[data-theme]`, which is how every danieldeusing
 * surface selects a theme and what lets the choice carry between them. But 35
 * components here still write `dark:` variants, and that variant compiles
 * against `.dark` — so dropping the class would leave those rules dead on the
 * two dark themes, which is light-on-light text exactly where it used to work.
 *
 * Syncing both is not a transitional hack. `data-theme` names WHICH of four
 * themes; `.dark` names whether this one is dark. They answer different
 * questions, and a component asking the second should not have to enumerate
 * the first.
 */
function DarkClassBridge() {
  const { resolvedTheme } = useTheme()
  useEffect(() => {
    document.documentElement.classList.toggle(
      'dark', DARK_THEMES.has(resolvedTheme ?? ''),
    )
  }, [resolvedTheme])
  return null
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  return (
    <NextThemesProvider
      attribute="data-theme"
      themes={[...THEMES]}
      // Warm is the system's own default and the one `:root` carries, so the
      // page is already correct before this provider mounts.
      defaultTheme="warm"
      enableSystem={false}
      // The SAME storage key every other surface uses. Picking a theme in the
      // cockpit is meant to carry into netmon and into here; a private key
      // would make this the one screen that forgets.
      storageKey="theme"
    >
      <DarkClassBridge />
      {children}
    </NextThemesProvider>
  )
}
