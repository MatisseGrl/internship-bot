-- Vue « offres_a_voir » : les offres affichées par /offres (dans_snapshot), moins celles où une
-- candidature existe déjà. Liée à la table offres : elle suit chaque mise à jour, rien à recopier.
-- Ordre : retenues, limites, à trancher, illisibles ; puis score de la grille décroissant.
create or replace view public.offres_a_voir
with (security_invoker = true) as
select
  row_number() over (order by o.ordre, o.score desc nulls last, o.entreprise, o.titre) as position,
  o.entreprise,
  o.titre,
  o.lieu,
  o.verdict,
  o.score,
  o.note_json ->> 'conditions' as conditions,
  o.url,
  o.cle
from (
  select
    offres.*,
    coalesce(note_json ->> 'statut', 'non notée') as verdict,
    case note_json ->> 'statut'
      when 'retenue' then 1
      when 'limite' then 2
      when 'a_trancher' then 3
      when 'illisible' then 4
      else 5
    end as ordre
  from public.offres
  where dans_snapshot
) o
where not exists (select 1 from public.candidatures c where c.cle_offre = o.cle)
order by position;

-- Mêmes droits que les autres objets du schéma : clé serveur seulement (pas d'accès anonyme).
revoke all on public.offres_a_voir from anon, authenticated;
