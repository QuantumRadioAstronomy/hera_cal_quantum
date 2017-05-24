'''Classes and Functions for running Firstcal.'''
import numpy as np
import aipy as a
import pylab as p
import time
import omnical
from heracal.omni import Antpol
import multiprocessing as mpr
import scipy.sparse as sps


def fit_line(phs, fqs, valid):
    '''Fit a line to data points (phs) at some given values (fqs).

    Args:
        phs : array of data points to fit.
        fqs : array of x-values corresponding to data points. Same shape as phs.
        valid : Boolean array indicating at which x-values to fit line.

    Returns:
        dt: slope of line
    '''
    fqs = fqs.compress(valid)
    dly = phs.compress(valid)
    B = np.zeros((fqs.size, 1)); B[:, 0] = dly
    A = np.zeros((fqs.size, 1)); A[:, 0] = fqs * 2 * np.pi  # ; A[:,1] = 1
    dt = np.linalg.lstsq(A, B)[0][0][0]
    return dt


def redundant_bl_cal_simple(d1, w1, d2, w2, fqs, window='none', finetune=True, verbose=False, average=False):
    '''Gets the phase differnce between two baselines by using the fourier transform and a linear fit to that residual slop.

    Args:
        d1,d2 (arrays): Data arrays to find phase difference between. First axis is time, second axis is frequency.
        w1,w2 (arrays): corrsponding data weight arrays.
        fqs (array): Array of frequencies in GHz.
        window (str, optional): Name of window function to use in fourier transform. Default is 'none'.
        finetune (bool, optional): Flag if you want to fine tune the phase fit with a linear fit. Default is true.
        verbose (bool, optional): Be verobse. Default is False.
        average (bool, optional): Average the data in time before applying analysis. collapses NXM -> 1XM.

    Returns
        delays (array): Array of delays (if average == False), or single delay.

'''
    d12 = d2 * np.conj(d1)  # note that this is d2/d1, not d1/d2 which leads to a reverse conjugation.
    # For 2D arrays, assume first axis is time.
    if average:
        if d12.ndim > 1:
            d12_sum = np.sum(d12, axis=0).reshape(1, -1)
            d12_wgt = np.sum(w1 * w1, axis=0).reshape(1, -1)
        else:
            d12_sum = d12.reshape(1, -1)
            d12_wgt = w1.reshape(1, -1) * w2.reshape(1, -1)
    else:
        d12_sum = d12
        d12_wgt = w1 * w2
    # normalize data to maximum so that we minimize fft articats from RFI
    d12_sum *= d12_wgt
    d12_sum = d12_sum / np.where(np.abs(d12_sum) == 0., 1., np.abs(d12_sum))
    window = a.dsp.gen_window(d12_sum[0, :].size, window=window)
    dlys = np.fft.fftfreq(fqs.size, fqs[1] - fqs[0])
    # FFT. Note d12_sum has weights multiplied in
    _phs = np.fft.fft(window * d12_sum, axis=-1)
    _phss = _phs
    _phss = np.abs(_phss)
    # get bin of phase.
    mxs = np.argmax(_phss, axis=-1)
    # Fine tune with linear fit.
    mxs[mxs > _phss.shape[-1] / 2] -= _phss.shape[-1]
    dtau = mxs / (fqs[-1] - fqs[0])
    # get bins of max and the bins around it.
    mxs = np.dot(mxs.reshape(len(mxs), 1), np.ones((1, 3), dtype=int)) + np.array([-1, 0, 1])
    # get actual average delays.
    taus = np.sum(_phss[np.arange(mxs.shape[0], dtype=int).reshape(-1, 1), mxs] * dlys[mxs], axis=-1) / np.sum(_phss[np.arange(mxs.shape[0]).reshape(-1, 1), mxs], axis=-1)
    dts = []
    if finetune:
        # loop over the linear fits
        for ii, (tau, d) in enumerate(zip(taus, d12_sum)):
            valid = np.where(d != 0, 1, 0)  # Throw out zeros, which NaN in the log below
            valid = np.logical_and(valid, np.logical_and(fqs > .11, fqs < .19))
            dly = np.angle(d * np.exp(-2j * np.pi * tau * fqs))
            dt = fit_line(dly, fqs, valid)
            dts.append(dt)
#            if plot:
#                p.subplot(411)
#                p.plot(fqs,np.angle(d12_sum[ii]), linewidth=2)
#                p.plot(fqs,d12_sum[ii], linewidth=2)
#                p.plot(fqs, np.exp((2j*np.pi*fqs*(tau+dt))+off))
#                p.hlines(np.pi, .1,.2,linestyles='--',colors='k')
#                p.hlines(-np.pi, .1,.2,linestyles='--',colors='k')
#                p.subplot(412)
#                p.plot(fqs,np.unwrap(dly)+2*np.pi*tau*fqs, linewidth=2)
#                p.plot(fqs,dly+2*np.pi*tau*fqs, linewidth=2,ls='--')
#                p.plot(fqs,2*np.pi*tau*fqs, linewidth=2,ls='-.')
#                p.plot(fqs,2*np.pi*(tau+dt)*fqs + off, linewidth=2,ls=':')
#                p.subplot(413)
#                p.plot(dlys, np.abs(_phs[ii]),'-.')
#                p.xlim(-400,400)
#                p.subplot(414)
#                p.plot(fqs,dly, linewidth=2)
#                p.plot(fqs,off+dt*fqs*2*np.pi, '--')
#                p.hlines(np.pi, .1,.2,linestyles='--',colors='k')
#                p.hlines(-np.pi, .1,.2,linestyles='--',colors='k')
#                print 'tau=', tau
#                print 'tau + dt=', tau+dt
#                p.xlabel('Frequency (GHz)', fontsize='large')
#                p.ylabel('Phase (radians)', fontsize='large')
#        p.show()
        dts = np.array(dts)
    if len(dts) == 0:
        dts = np.zeros_like(taus)
    info = {'dtau': dts, 'mx': mxs}
    if verbose: print info, taus, taus + dts
    return (taus + dts) / 1e9  # convert to seconds


class FirstCalRedundantInfo(omnical.info.RedundantInfo):
    '''
        FirstCalRedundantInfo class that interfaces to the FirstCal class
        for running firstcal. It subclasses the info.RedundantInfo class in omnical.
        The extra meta data added to the RedundantInfo object from omnical are:
    
    Attributes:
        self.nant : number of antennas
        self.A:  coefficient matrix for firstcal delay calibration. (Nmeasurements, Nants).
                 Measurements are ratios of redundant baselines.
        self.reds: list of redundant baselines.
        self.bl_pairs: list of redundant baseline pairs.
        self.antloc: array of antenna positions in the order of self.subsetant 
        self.ubl: list of unique baselines 
    '''
    def __init__(self, nant):
        '''Initialize with number of antennas.
        
        Args:
            nant (int): number of antennas.
        
        Attributes:
            nant (int): number of antennas 
            
        '''
        omnical.info.RedundantInfo.__init__(self)
        self.nant = nant

    def bl_order(self):
        '''Returns expected order of baselines.

        Return:
            (i,j) baseline tuples in the order that they should appear in data.
            Antenna indicies are in real-world order
            (as opposed to the internal ordering used in subsetant).
        '''
        return [(Antpol(self.subsetant[i], self.nant), Antpol(self.subsetant[j], self.nant)) for (i, j) in self.bl2d]

    def order_data(self, dd):
        """Create a data array ordered for use in _omnical.redcal.

        Args:
            dd (dict): dictionary whose keys are (i,j) antenna tuples; antennas i,j should be ordered to reflect
                       the conjugation convention of the provided data.  'dd' values are 2D arrays of (time,freq) data.
        Return:
            array: array whose ordering reflects the internal ordering of omnical. Used to pass into pack_calpar
        """
        d = []
        for i, j in self.bl_order():
            bl = (i.ant(), j.ant())
            pol = i.pol() + j.pol()
            try: d.append(dd[bl][pol])
            except(KeyError): d.append(dd[bl[::-1]][pol[::-1]].conj())
        return np.array(d).transpose((1, 2, 0))

    def bl_index(self, bl):
        '''Gets the baseline index from bl_order for a given baseline.
        
        Args:
            bl (tuple): antenna pair tuple.
        
        Return:
            int: index of baseline in internal ordering.
            
        '''
        try: return self._bl2ind[bl]
        except(AttributeError):
            self._bl2ind = {}
            for x, b in enumerate(self.bl_order()): self._bl2ind[b] = x
            return self._bl2ind[bl]

    def blpair_index(self, blpair):
        '''Gets the index of baseline pairs in A matrix

        Args:
            blpair (tuple): tuple of antenna pair tuples.

        Return:
            int: index of baseline pair in internal ordering of A matrix.
        '''
        try: return self._blpair2ind[blpair]
        except:
            self._blpair2ind = {}
            for x, bp in enumerate(self.bl_pairs): self._blpair2ind[bp] = x
            return self._blpair2ind[blpair]

    def blpair2antind(self, blpair):
        '''Get indexes of antennas in blpair in internal ordering.
        
        Args:
            blpair (tuple): tuple of antenna pair tuples.
        
        Return:
            tuple: tuple (4) of antenna indices in internal ordering.
        '''
          
        try: return self._blpair2antind[blpair]
        except:
            self._blpair2antind = {}
            for bp in self.bl_pairs: self._blpair2antind[bp] = map(self.ant_index, np.array(bp).flatten())
            return self._blpair2antind[blpair]

    def init_from_reds(self, reds, antpos):
        '''
            Initialize RedundantInfo from a list where each entry is a group of redundant baselines.
            Each baseline is a (i,j) tuple, where i,j are antenna indices.  To ensure baselines are
            oriented to be redundant, it may be necessary to have i > j.  If this is the case, then
            when calibrating visibilities listed as j,i data will have to be conjugated (use order_data).
            After initializing, the coefficient matrix for deducing delay solutions per antennas (for firstcal)
            is created by modeling it as per antenna delays.

        Args:
            reds (list): list of lists of antenna pairs.
            antpos (array): array of antenna positions in internal antenna order (self.subsetant).
        '''
        self.reds = [[(int(i), int(j)) for i, j in gp] for gp in reds]
        self.init_same(self.reds)
        # new stuff for first cal
        # get a list of the pairs of baselines
        self.bl_pairs = [(bl1, bl2) for ublgp in reds for i, bl1 in enumerate(ublgp) for bl2 in ublgp[i + 1:]]
        # initialize the coefficient matrix for least squares.
        A = np.zeros((len(self.bl_pairs), len(self.subsetant)))
        # populate matrix with coefficients. The equation for blpair ((a1,a2), (a3,a4))
        # the delay difference is d1 - d2 - d3 + d4
        for n, bp in enumerate(self.bl_pairs):
            i, j, k, l = self.blpair2antind(bp)
            A[n, i] += 1
            A[n, j] += -1
            A[n, k] += -1
            A[n, l] += 1
        self.A = A
        # Don't really need to have these.
        self.antloc = antpos.take(self.subsetant, axis=0).astype(np.float32)
        self.ubl = np.array([np.mean([antpos[int(j)] - antpos[int(i)] for i, j in ublgp], axis=0) for ublgp in reds], dtype=np.float32)

    def get_reds(self):
        '''Returns redundancies.

        Return:
            list: list if list of redundant baselines.
        '''
        try: return self.reds
        except(AttributeError):
            print 'Initialize info class!'


class FirstCal(object):
    '''FirstCal class that is used to run firstcal.

    Attributes:
        data: dictionary of visibilities
        fqs: frequency array
        info: FirstCalRedundantInfo object
        wgts: dictionary of wgts. see data.
    '''
    def __init__(self, data, wgts, fqs, info):
        '''Initialization of FirstCal object.

        Args:
            data (dict): dictionary of visibilities with keys being antenna pair tuples.
                Values should be 2D arrays with first axis corresponding to time 
                and second corresponding to frequencies.
            wgts (dict): dictionary of weights with keys being antenna pair tuples.
                see data for format.
            fqs (array): array of frequencies corresponding to visibilities.
            info: FirstCalRedundantInfo object. This describes the redundancies 
                and has the proper least square matrices.
        '''
        self.data = data
        self.fqs = fqs
        self.info = info
        self.wgts = wgts

    def data_to_delays(self, **kwargs):
        '''
            Returns:
                dict: dictionary with keys baseline pair and values solved delays.
        '''
        verbose = kwargs.get('verbose', False)
        blpair2delay = {}
        blpair2offset = {}
        dd = self.info.order_data(self.data)
        ww = self.info.order_data(self.wgts)
        # loop over baseline pairs and solve for delay derived by that pair.
        for (bl1, bl2) in self.info.bl_pairs:
            if verbose:
                print (bl1, bl2)
            d1 = dd[:, :, self.info.bl_index(bl1)]
            w1 = ww[:, :, self.info.bl_index(bl1)]
            d2 = dd[:, :, self.info.bl_index(bl2)]
            w2 = ww[:, :, self.info.bl_index(bl2)]
            delay = redundant_bl_cal_simple(d1, w1, d2, w2, self.fqs, **kwargs)
            blpair2delay[(bl1, bl2)] = delay
        return blpair2delay

    def get_N(self, nblpairs):
        ''' Returns noise matrix.
            
        Currently this is set to the identity.    
            
        Returns:
            sparse array: identity matrix
        '''
        return sps.eye(nblpairs)

    def get_M(self, **kwargs):
        '''Returns the measurement matrix.
        
        Returns:
            array: vector of measured delays.'''
        blpair2delay = self.data_to_delays(**kwargs)
        sz = len(blpair2delay[blpair2delay.keys()[0]])
        M = np.zeros((len(self.info.bl_pairs), sz))
        for pair in blpair2delay:
            M[self.info.blpair_index(pair), :] = blpair2delay[pair]
        return M

    def run(self, **kwargs):
        '''Runs firstcal after the class initialized.

        Returns:
            dict: antenna delay pair with delay in nanoseconds.

        Attributes:
            M: vector of measured delays.
            _N: inverse of the noise matrix.
            A: least squares coefficient matrix.
            xhat: dictionary of solved for delays.
        '''
        verbose = kwargs.get('verbose', False)
        # make measurement matrix
        print "Geting M,O matrix"
        self.M = self.get_M(**kwargs)
        print "Geting N matrix"
        N = self.get_N(len(self.info.bl_pairs))
        # XXX This needs to be addressed. If actually do invers, slows code way down.
        # self._N = np.linalg.inv(N)
        self._N = N  # since just using identity now

        # get coefficients matrix,A
        self.A = sps.csr_matrix(self.info.A)
        print 'Shape of coefficient matrix: ', self.A.shape

        # solve for delays
        print "Inverting A.T*N^{-1}*A matrix"
        invert = self.A.T.dot(self._N.dot(self.A)).todense()  # make it dense for pinv
        dontinvert = self.A.T.dot(self._N.dot(self.M))  # converts it all to a dense matrix
        # definitely want to use pinv here and not solve since invert is probably singular.
        self.xhat = np.dot(np.linalg.pinv(invert), dontinvert)
        # turn solutions into dictionary
        return dict(zip(map(Antpol,self.info.subsetant,[self.info.nant]*len(self.info.subsetant)), self.xhat))
