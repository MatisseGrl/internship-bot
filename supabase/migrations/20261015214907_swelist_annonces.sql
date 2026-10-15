-- Inventaire privé des alertes SWElist, séparé du registre des offres du bot.
-- Une correspondance par entreprise/titre n'est qu'une suggestion de doublon.
begin;

create table if not exists public.swelist_annonces (
  simplify_id text primary key,
  date_mail date not null,
  id_mail text not null,
  entreprise text not null,
  intitule text not null,
  lien_simplify text not null unique,
  premier_filtre text not null,
  raison text not null,
  bot_cle_candidate text references public.offres(cle) on delete set null,
  rapprochement text not null default 'aucun',
  label_humain smallint check (label_humain in (0, 1)),
  score_fit double precision check (score_fit between 0 and 1),
  verdict_ml text,
  version_modele text,
  evalue_le timestamptz
);

create index if not exists swelist_rapprochement_idx
  on public.swelist_annonces (rapprochement);
create index if not exists swelist_verdict_idx
  on public.swelist_annonces (verdict_ml);

alter table public.swelist_annonces enable row level security;
revoke all privileges on public.swelist_annonces from public, anon, authenticated;

commit;
