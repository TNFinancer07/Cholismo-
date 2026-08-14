/** Bouton de détachement (D-117). */
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DetachButton } from './detach-button'

const vraiOpen = window.open
const vraieRecherche = window.location.search

function poserRecherche(search: string) {
  Object.defineProperty(window, 'location', {
    value: { ...window.location, search, pathname: '/' }, writable: true, configurable: true,
  })
}

beforeEach(() => poserRecherche(''))
afterEach(() => { window.open = vraiOpen; poserRecherche(vraieRecherche); vi.restoreAllMocks() })

describe('bouton de détachement', () => {
  it('ouvre une fenêtre indépendante pour le panneau demandé', () => {
    const open = vi.fn((_url?: string | URL, _n?: string, _f?: string) => ({}) as Window)
    window.open = open as unknown as typeof window.open
    render(<DetachButton panelId="OFG" />)
    fireEvent.click(screen.getByTestId('detach-OFG'))
    expect(open).toHaveBeenCalledOnce()
    expect(String(open.mock.calls[0][0])).toContain('panel=OFG')
  })

  it('DIT quand la popup est bloquée — sinon on cherche une fenêtre qui n\'existe pas', () => {
    window.open = (() => null) as unknown as typeof window.open
    render(<DetachButton panelId="C6" />)
    const b = screen.getByTestId('detach-C6')
    fireEvent.click(b)
    expect(b.textContent).toContain('bloquée')
    expect(b.getAttribute('title')).toContain('BLOQUÉE')
  })

  it("ne s'affiche PAS dans une fenêtre déjà détachée", () => {
    poserRecherche('?panel=OFG')
    render(<DetachButton panelId="OFG" />)
    expect(screen.queryByTestId('detach-OFG')).toBeNull()
  })

  it('porte un libellé accessible en plus de l\'icône', () => {
    render(<DetachButton panelId="OFG" />)
    expect(screen.getByTestId('detach-OFG').textContent).toContain('détacher')
  })
})
