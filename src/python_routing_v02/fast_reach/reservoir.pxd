cdef struct QH:
    float resoutflow
    float reslevel

cdef void levelpool_physics(float dt,
        float qi0,
        float qi1,
        float ql,
        float ar,
        float we,
        float maxh,
        float wc,
        float wl,
        float dl,
        float oe,
        float oc,
        float oa,
        float H0,
        QH *rv) nogil