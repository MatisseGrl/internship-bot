-- Notation v2 : une seule ligne principale par entreprise dans les listes accessibles/tentables.
-- Les autres offres de l'entreprise gardent leur `liste` (sous-ligne « autres localisations »).
-- Ex. Databricks n'autorise qu'une candidature par 30 jours : une seule ligne principale (Amsterdam).
alter table public.notation_v2 add column if not exists ligne_principale boolean not null default false;

-- La vue lit désormais la ligne principale (choisie par le calcul, avec choix imposés Databricks/Amazon) au lieu de la deviner.
create or replace view public.offres_accessibles
with (security_invoker = true) as
select
  row_number() over (order by (liste = 'accessible') desc, realisme desc, competences desc, interet desc, entreprise) as position,
  liste, entreprise, titre, lieu, interet, competences, realisme, manque, etiquettes, conditions, url, cle,
  (select count(*) from public.notation_v2 o
    where o.entreprise = n.entreprise and o.liste is not null and not o.ligne_principale) as autres_localisations
from public.notation_v2 n
where n.liste is not null
  and n.ligne_principale
  and not exists (select 1 from public.candidatures c where c.cle_offre = n.cle)
order by position;
