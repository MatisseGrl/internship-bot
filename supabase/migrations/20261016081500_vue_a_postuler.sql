-- Vue lisible du classement : offres présentes, éligibles, sans candidature ni doublon,
-- déjà triées. `position` numérote cette liste ; `rang_global` renvoie à la table classement.
-- security_invoker : la vue applique les droits de celui qui la lit (RLS de classement).
create or replace view public.a_postuler
with (security_invoker = true) as
select
  row_number() over (order by rang) as position,
  entreprise,
  titre,
  lieu,
  round(score_retenue::numeric, 3) as score,
  url,
  source,
  rang as rang_global
from public.classement
where present and eligible and not deja_candidature and doublon_du_rang is null
order by rang;

revoke all privileges on public.a_postuler from public, anon, authenticated;
