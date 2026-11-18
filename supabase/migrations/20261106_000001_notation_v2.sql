-- Notation v2 des offres (intérêt / compétences / réalisme), deuxième filtre après config.yaml.
-- Table séparée : ne touche ni « offres », ni « candidatures », ni la vue « offres_a_voir ».
-- Clé : « entreprise \x1f identifiant » (même convention que « offres », sans clé étrangère
-- car certaines offres notées ne sont plus dans « offres »).
create table if not exists public.notation_v2 (
  cle text primary key,
  entreprise text not null,
  identifiant text not null,
  titre text,
  lieu text,
  url text,
  etat text not null,           -- note | postulee | refusee | a_relancer | retiree | ineligible
  priorite text,                -- A | B | C | D (seulement si etat = note)
  liste text,                   -- accessible | tentable (UE/EEE, Data/ML, durée 12 semaines à 6 mois)
  interet smallint,
  competences smallint,
  realisme smallint,
  manque jsonb not null default '[]',
  etiquettes jsonb not null default '[]',
  conditions text,
  motif text,                   -- motif d'inéligibilité ou détail de lecture
  zone text,
  preuves jsonb not null default '{}',
  maj_le timestamptz not null default now()
);
alter table public.notation_v2 enable row level security;
revoke all on public.notation_v2 from anon, authenticated;

-- Une ligne par entreprise : la meilleure offre (réalisme, compétences, intérêt), accessibles avant tentables.
create or replace view public.offres_accessibles
with (security_invoker = true) as
select
  row_number() over (order by (liste = 'accessible') desc, realisme desc, competences desc, interet desc, entreprise) as position,
  liste, entreprise, titre, lieu, interet, competences, realisme, manque, etiquettes, conditions, url, cle
from (
  select distinct on (n.entreprise) n.*
  from public.notation_v2 n
  where n.liste is not null
    and not exists (select 1 from public.candidatures c where c.cle_offre = n.cle)
  order by n.entreprise, (n.liste = 'accessible') desc, n.realisme desc, n.competences desc, n.interet desc
) t
order by position;
