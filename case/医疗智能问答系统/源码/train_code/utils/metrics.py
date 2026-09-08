import numpy as np
from sklearn.metrics import cohen_kappa_score, confusion_matrix, classification_report

def quadratic_kappa(y_true, y_pred):
    return cohen_kappa_score(y_true, y_pred, weights='quadratic')