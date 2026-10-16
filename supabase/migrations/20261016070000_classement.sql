-- Classement officiel des offres (bot et SWElist), calculé localement par
-- agent_local/tri_texte.py : modèle sur le texte, règles d'éligibilité, rang et doublons.
-- Une offre qui disparaît des sources reste avec present = false et rang = null.
begin;

create table if not exists public.classement (
  source text not null check (source in ('bot', 'swelist')),
  identifiant text not null,
  rang integer,
  present boolean not null,
  entreprise text not null,
  titre text not null,
  lieu text,
  url text,
  base text not null check (base in ('texte', 'titre')),
  score_fit double precision check (score_fit between 0 and 1),
  verdict_fit text,
  score_retenue double precision check (score_retenue between 0 and 1),
  eligible boolean not null,
  motifs jsonb not null default '[]'::jsonb,
  deja_candidature boolean not null,
  doublon_du_rang integer,
  version text not null,
  classe_le timestamptz not null,
  primary key (source, identifiant)
);

create index if not exists classement_rang_idx on public.classement (rang);
create index if not exists classement_eligible_idx on public.classement (eligible, present);

alter table public.classement enable row level security;
revoke all privileges on public.classement from public, anon, authenticated;

commit;
