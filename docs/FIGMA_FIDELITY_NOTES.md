# Figma Fidelity Notes

Phase 1 uses the approved published prototype at
`https://heart-human-86042979.figma.site/` as a visual reference. The source did
not expose node-level Figma metadata, so the values below are intentionally
isolated in `frontend/smart-counselling/src/styles.scss` for later adjustment.

## Approximated values

- Spacing uses a reusable 4/8/12/16/20/24/32px scale inferred from the rendered prototype.
- Heading, body, label, and metric font sizes were visually matched; original Figma text styles were unavailable.
- Card radii use 12px, controls use 8px, and larger containers may use 16px.
- The prototype primary color was sampled as approximately `#4a5bdb`. Tenant branding is exposed separately as `--sc-tenant-primary` and does not silently replace the counselling palette.
- Borders use low-contrast neutral greys and card shadows are approximated from the published render.
- Bootstrap Icons already loaded by the ERP shell replace unavailable Figma-exported icons.
- Responsive breakpoints are 1200px, 768px, and 480px. These were chosen from the existing Bootstrap shell and the observed prototype behavior, not Figma constraints.
- Hover, keyboard-focus, disabled, error, and reduced-motion states were reconstructed because all original interactive variants were not reachable.
- The seven-step labels are shortened so the stepper remains readable inside the existing ERP content column.

## Intentional Phase 1 differences

- Angular renders only the content region; the existing Flask/Jinja sidebar and topbar remain authoritative.
- Counselling-session metrics are zero and recent sessions use an empty state until Phase 2 creates the tenant-scoped session model.
- OTP and authorized search buttons are visibly disabled because those behaviors are outside Phase 1.
- Prototype copy referring to AI is not used. The written specification defines a deterministic recommendation engine for later phases.

## Later fidelity pass

If a selected-frame Figma Design URL becomes available, verify tokens, exported
assets, typography, constraints, interaction variants, and component hierarchy
against the reconstruction before broad rollout.

## Phase 4 additions

The Profile, Goals, and Skills screens continue the approved prototype-guided reconstruction. Node-level Figma metadata remains unavailable, so exact card gaps, segmented-control heights, chip wrapping, mobile breakpoints, and selected/hover/focus colors are approximated through the existing reusable Smart Counselling tokens. The questionnaire favors accessible native controls and counselling-friendly targets over unverified pixel-level detail.
