import cython

from fortran_wrappers cimport c_levelpool_physics


@cython.boundscheck(False)
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
        QH *rv) nogil:
    cdef:
        float H1 = 0.0
        float qo1 = 0.0

    c_levelpool_physics(
        &dt,
        &qi0,
        &qi1,
        &ql,
        &ar,
        &we,
        &maxh,
        &wc,
        &wl,
        &dl,
        &oe,
        &oc,
        &oa,
        &H0,
        &H1,
        &qo1)
    rv.reslevel = H1
    rv.resoutflow = qo1


cpdef compute_reservoir_kernel(float dt,
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
        float H0):

    cdef QH rv
    cdef QH *out = &rv

    levelpool_physics(dt,
        qi0,
        qi1,
        ql,
        ar,
        we,
        maxh,
        wc,
        wl,
        dl,
        oe,
        oc,
        oa,
        H0,
        out)

    return rv





@cython.boundscheck(False)
cpdef float[:,:] compute_reservoir(const float[:] boundary,
                                    const float[:,:] previous_state,
                                    const float[:,:] parameter_inputs,
                                    float[:,:] output_buffer) nogil:
    """
    Compute a reservoir

    Arguments:
        boundary: [qi0, qi1]
        previous_state: Previous state for each node in the reach [qdp, velp, depthp]
        parameter_inputs: Parameterization of the reach at node.
            dt,ql,ar,we,maxh,wc,wl,dl,oe,oc,oa,H0
        output_buffer: Current state [H1, qo0]
    """
    cdef QH rv
    cdef QH *out = &rv

    cdef:
        float dt, ql, ar, we, maxh, wc, wl, dl, oe, oc, oa, H0
        Py_ssize_t i

    # check that previous state, parameter_inputs and output_buffer all have same axis 0
    cdef Py_ssize_t rows = parameter_inputs.shape[0]
    if rows != output_buffer.shape[0]:
        raise ValueError("axis 0 of input arguments do not agree")

    # check bounds
    if boundary.shape[0] < 2:
        raise IndexError
    if parameter_inputs.shape[1] < 12:
        raise IndexError
    if output_buffer.shape[1] < 2:
        raise IndexError

    cdef float qi0 = boundary[0]
    cdef float qi1 = boundary[1]

    for i in range(rows):
        dt = parameter_inputs[i, 0]
        ql = parameter_inputs[i, 1]
        ar = parameter_inputs[i, 2]
        we = parameter_inputs[i, 3]
        maxh = parameter_inputs[i, 4]
        wc = parameter_inputs[i, 5]
        wl = parameter_inputs[i, 6]
        dl = parameter_inputs[i, 7]
        oe = parameter_inputs[i, 8]
        oc = parameter_inputs[i, 9]
        oa = parameter_inputs[i, 10]
        H0 = parameter_inputs[i, 11]

        levelpool_physics(dt,
            qi0,
            qi1,
            ql,
            ar,
            we,
            maxh,
            wc,
            wl,
            dl,
            oe,
            oc,
            oa,
            H0,
            out)

        output_buffer[i, 0] = out.reslevel
        output_buffer[i, 1] = out.resoutflow

    return output_buffer