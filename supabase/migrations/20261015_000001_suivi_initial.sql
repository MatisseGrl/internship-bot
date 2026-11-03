-- Registre privé du bot de stages. Aucune donnée personnelle n'est insérée ici.
-- Les tables sont dans public pour un futur tableau de bord, mais RLS est activée
-- et aucun accès anon/authenticated n'est accordé à cette étape.

begin;

create table if not exists public.offres (
  cle text primary key,
  entreprise text not null,
  identifiant text not null,
  titre text,
  lieu text,
  url text,
  texte text,
  categorie_note text,
  note_json jsonb,
  score numeric(5, 2),
  dans_snapshot boolean not null default false,
  vu_le timestamptz not null default now(),
  unique (entreprise, identifiant)
);

create table if not exists public.candidatures (
  cle_offre text primary key references public.offres(cle),
  statut text not null,
  cv text,
  preuve text,
  modifie_le timestamptz not null default now()
);

create table if not exists public.mails (
  boite text not null,
  identifiant_message text not null,
  recu_le timestamptz,
  expediteur text,
  objet text,
  categorie text not null,
  cle_offre text references public.offres(cle),
  justification text,
  traite_le timestamptz not null default now(),
  primary key (boite, identifiant_message)
);

create table if not exists public.evenements_candidature (
  id bigint generated always as identity primary key,
  cle_offre text not null references public.offres(cle),
  type_evenement text not null,
  source text,
  details jsonb not null default '{}'::jsonb,
  cree_le timestamptz not null default now()
);

create index if not exists offres_snapshot_score_idx
  on public.offres (dans_snapshot, score desc nulls last);
create index if not exists candidatures_statut_idx
  on public.candidatures (statut);
create index if not exists mails_offre_idx
  on public.mails (cle_offre);
create index if not exists evenements_offre_date_idx
  on public.evenements_candidature (cle_offre, cree_le desc);

alter table public.offres enable row level security;
alter table public.candidatures enable row level security;
alter table public.mails enable row level security;
alter table public.evenements_candidature enable row level security;

revoke all privileges on table
  public.offres,
  public.candidatures,
  public.mails,
  public.evenements_candidature
from public, anon, authenticated;

commit;

-- Après exécution : quatre tables vides, sans politique RLS et non accessibles
-- aux rôles anon/authenticated. La clé secrète service_role reste réservée au backend.
-- Les droits du futur tableau de bord seront ajoutés séparément et testés.
