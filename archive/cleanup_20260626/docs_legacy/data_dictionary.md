# Data Dictionary

| Symbol | Meaning | Notes |
|---|---|---|
| `X` | Whether candidate CCP `j` is opened | First-stage binary variable |
| `V` | Medical staff assigned to CCP `j` | First-stage nonnegative integer |
| `U` | CCP ambulances assigned to CCP `j` | First-stage nonnegative integer |
| `Y` | Supplies allocated from hospital `h` to CCP `j` | First-stage nonnegative integer |
| `FI` | Casualties transported from disaster area `i` to CCP `j` | Second-stage nonnegative continuous |
| `FO` | Treated ambulance-required casualties transferred from CCP `j` to hospital `h` | Only for `moderate` and `severe`; second-stage nonnegative continuous |
| `RM` | Casualties remaining in disaster area `i` at end of period `t` | Second-stage nonnegative continuous |
| `REG` | Casualties registered at CCP `j` in period `t` | Equals incoming `FI`; second-stage nonnegative continuous |
| `TRT` | Casualties under treatment at CCP `j` during period `t` | Rolling sum over treatment time `tau_l`; second-stage nonnegative continuous |
| `WAT` | Treated ambulance-required casualties waiting for hospital transfer | Only for `moderate` and `severe`; second-stage nonnegative continuous |
| `xi_ilts` | New casualties at disaster area `i`, severity `l`, period `t`, scenario `s` | Random variable realization |
| `u_ijts` | Available capacity proportion for disaster-area-to-CCP road | Random variable realization in `[0,1]` |
| `w_jhts` | Available capacity proportion for CCP-to-hospital road | Random variable realization in `[0,1]` |
| `h_hts` | Hospital receiving capacity | Random variable realization |
