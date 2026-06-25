"""Machine-readable data dictionary for reports and documentation."""

VARIABLE_DICTIONARY = {
    "X": "Binary first-stage decision: whether CCP j is opened.",
    "V": "Nonnegative integer first-stage decision: medical staff assigned to CCP j.",
    "U": "Nonnegative integer first-stage decision: CCP ambulances assigned to CCP j.",
    "Y": "Nonnegative integer first-stage decision: supplies allocated from hospital h to CCP j.",
    "FI": "Continuous second-stage flow from disaster area i to CCP j.",
    "FO": "Continuous second-stage hospital transfer flow for L_Amb casualties.",
    "RM": "Continuous second-stage casualties remaining in disaster area i.",
    "REG": "Continuous second-stage casualties registered at CCP j.",
    "TRT": "Continuous second-stage casualties under treatment at CCP j.",
    "WAT": "Continuous second-stage treated L_Amb casualties waiting for hospital transfer.",
}

