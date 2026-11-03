-- Table « offres_masquees » : offres qu'on ne veut plus voir dans offres_a_voir sans y avoir
-- postulé (ex : même poste publié dans une autre ville, déjà candidaté ailleurs).
-- Retirer une ligne fait revenir l'offre.
create table if not exists public.offres_masquees (
  cle text primary key references public.offres (cle),
  raison text not null,
  masquee_le timestamptz not null default now()
);
alter table public.offres_masquees enable row level security;
revoke all on public.offres_masquees from anon, authenticated;

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
  and not exists (select 1 from public.offres_masquees m where m.cle = o.cle)
order by position;

revoke all on public.offres_a_voir from anon, authenticated;
