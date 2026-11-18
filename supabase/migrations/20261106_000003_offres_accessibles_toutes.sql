-- Décision de Matisse (6 nov.) : plus de regroupement « une ligne par entreprise ». La vue liste TOUTES les offres
-- accessibles / tentables (hors déjà postulées). Visa : simple étiquette (US...), jamais une exclusion.
-- La colonne `ligne_principale` reste (utile pour Databricks : une seule candidature par 30 jours) mais n'est plus lue par la vue.
drop view if exists public.offres_accessibles;
create view public.offres_accessibles
with (security_invoker = true) as
select
  row_number() over (order by (liste = 'accessible') desc, realisme desc, competences desc, interet desc, entreprise, titre) as position,
  liste, entreprise, titre, lieu, interet, competences, realisme, manque, etiquettes, conditions, url, cle
from public.notation_v2 n
where n.liste is not null
  and not exists (select 1 from public.candidatures c where c.cle_offre = n.cle)
order by position;
