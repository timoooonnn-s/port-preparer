SYNTHETIC FIXTURES - NOT CAPTURED FROM A DEVICE
==============================================

A deliberately inconsistent two-switch fleet, written by hand to exercise the survey's
cross-device checks. Every inconsistency here is intentional:

  i-sid 2500695  named differently on the two switches           -> isid-name-conflict
  i-sid 2500696  ELAN on a1, CVLAN on a2                         -> isid-model-split
  i-sid 2500699  configured on a1, no remote BEB advertises it    -> isid-orphan
  i-sid 2519999  prefix 251 is the legacy prod variant, and the
                 number encodes vlan 9999 while it is bound to
                 c-vid 700                                       -> isid-vlan-mismatch
  vlan 800       named differently on the two switches            -> vlan-name-conflict
  vlan 801       mapped to i-sid 2500801 on a1 and 2700801 on a2  -> vlan-multiple-isids

Column widths follow real VOSS output. If you edit these, keep substitutions width-preserving.
