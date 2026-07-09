"""Minimalist lo-fi HUD: HP (bottom-left), weapon/ammo (bottom-right), keys
(top-right), crosshair. Pure pygame.draw + small bitmap font, no Surface
allocation beyond what pygame.font.render necessarily returns per string.
"""

from __future__ import annotations

import math

import pygame

from .sim import WEAPONS, LIGHTNING_RECHARGE_TICKS, PLAYER_HP
from .render import KEY_COLORS

_FONT_CACHE: dict[int, "pygame.font.Font"] = {}


def _font(size: int) -> "pygame.font.Font":
    from .menus import get_font
    return get_font(size)


AMMO_LABEL = {"pistol": "9mm", "smg": "9mm", "shotgun": "shell", "rail": "cell", "tau": "cell"}


class HUD:
    def draw(self, surf: "pygame.Surface", session, mouse_pos=None) -> None:
        w, h = surf.get_size()
        self._draw_hp(surf, session, h)
        self._draw_weapon(surf, session, w, h)
        self._draw_keys(surf, session, w)
        if mouse_pos is not None:
            self._draw_crosshair(surf, session, mouse_pos)

    def _draw_hp(self, surf, session, h):
        bar_w, bar_h = 70, 5
        x, y = 6, h - 14
        low = session.hp < 35 and not session.dead
        pulse = 0.5 + 0.5 * math.sin(session.tick_count * 0.35) if low else 1.0
        color = (int(190 * pulse) + 40, 40, 40) if low else (235, 235, 235)
        pygame.draw.rect(surf, (40, 40, 40), (x, y, bar_w, bar_h))
        frac = max(0.0, min(1.0, session.hp / PLAYER_HP))
        pygame.draw.rect(surf, color, (x, y, int(bar_w * frac), bar_h))
        pygame.draw.rect(surf, (90, 90, 90), (x, y, bar_w, bar_h), 1)
        img = _font(11).render(f"{max(0, int(session.hp))}", True, color)
        surf.blit(img, (x, y - 12))

    def _draw_weapon(self, surf, session, w, h):
        name = session.weapon
        f = _font(11)
        if name == "lightning":
            frac = min(1.0, session.lightning_charge / LIGHTNING_RECHARGE_TICKS)
            cx, cy, r = w - 16, h - 20, 9
            pygame.draw.circle(surf, (40, 40, 50), (cx, cy), r, 1)
            if frac > 0.0:
                start = -math.pi / 2
                end = start + frac * 2 * math.pi
                steps = max(1, int(frac * 24))
                pts = [(cx, cy)]
                for i in range(steps + 1):
                    a = start + (end - start) * (i / max(1, steps))
                    pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
                if len(pts) >= 3:
                    color = (120, 240, 255) if frac >= 1.0 else (70, 130, 150)
                    pygame.draw.polygon(surf, color, [(int(px), int(py)) for px, py in pts])
            label = f.render("LIGHTNING", True, (200, 235, 255))
            surf.blit(label, (w - 16 - label.get_width() - 16, h - 34))
        else:
            ammo_t = AMMO_LABEL.get(name)
            count = "∞" if ammo_t is None else str(session.ammo.get(ammo_t, 0))
            label = f.render(f"{name.upper()}  {count}", True, (230, 230, 230))
            surf.blit(label, (w - label.get_width() - 8, h - 16))

    def _draw_keys(self, surf, session, w):
        x = w - 10
        y = 8
        for key in sorted(session.keys):
            color = KEY_COLORS.get(key, (200, 170, 60))
            pygame.draw.circle(surf, color, (x, y + 4), 4)
            pygame.draw.circle(surf, (0, 0, 0), (x, y + 4), 4, 1)
            x -= 12

    def _draw_crosshair(self, surf, session, mouse_pos):
        mx, my = mouse_pos
        weapon = WEAPONS.get(session.weapon, {})
        if session.weapon == "lightning":
            frac_ready = min(1.0, session.lightning_charge / LIGHTNING_RECHARGE_TICKS)
            expand = (1.0 - frac_ready) * 4.0
        else:
            maxcd = weapon.get("cd") or 1
            expand = (session.cooldown / maxcd) * 4.0 if maxcd else 0.0
        size = 3 + expand
        color = (220, 240, 240)
        pygame.draw.line(surf, color, (mx - size, my), (mx - 2, my), 1)
        pygame.draw.line(surf, color, (mx + 2, my), (mx + size, my), 1)
        pygame.draw.line(surf, color, (mx, my - size), (mx, my - 2), 1)
        pygame.draw.line(surf, color, (mx, my + 2), (mx, my + size), 1)
