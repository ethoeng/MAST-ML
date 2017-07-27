import os
import numpy as np
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import KFold
from sklearn.model_selection import ShuffleSplit
from KFoldCV import KFoldCV
from LeaveOutPercentCV import LeaveOutPercentCV
from plot_data.PlotHelper import PlotHelper
from SingleFit import SingleFit
from SingleFit import timeit
from custom_features import cf_help
from FeatureOperations import FeatureIO
from DataHandler import DataHandler
import pandas as pd
import copy
import logging
logger = logging.getLogger()

class ParamGridSearch(SingleFit):
    """Parameter optimization by grid search
        Only 4 parameters may be optimized at a time.
   
    Args:
        training_dataset, (Should be the same as testing_dataset)
        testing_dataset, (Should be the same as training_dataset)
        model,
        save_path,
        xlabel, 
        ylabel, see parent class.
        param_1 <str>: parameter string made up of semicolon-delimited pieces
            Piece 1: The word 'model' or a custom feature class.method string, 
                        e.g. DBTT.calculate_EffectiveFluence,
                        where the custom module has the same name as the 
                        custom class, and resides inside 
                        the custom_features folder
            Piece 2: The parameter name
            Piece 3: The parameter type. Use only:
                        'int', 'float', 'bool', 'str'
                        (Some sklearn model
                        hyperparameters are type-sensitive)
            Piece 4: The series type. Use:
                        'discrete': List will be given in piece 5
                                'bool' and 'str' MUST use 'discrete'
                        'continuous': Range and step will be given in piece 5
                        'continuous-log: Range and step will be given in piece 5
            Piece 5: A colon-delimited list of 
                    (a) a discrete list of values to grid over, OR
                    (b) start, end, number of points: 
                        numpy's np.linspace or np.logspace
                        function will be used to generate this list,
                        using an inclusive start and inclusive end
                    A parameter with only one discrete value will not be
                    considered as an 'optimized' parameter.
        param_2 <str> etc. 
        fix_random_for_testing <int>: 0 - use random numbers
                                      1 - fix randomizer for testing
        num_cvtests <int>: Number of CV tests for each validation step
        additional_feature_methods <str>: comma-delimited string, or
            a list, of semicolon-delimited pieces, formatted like:
            class.method;parameter1:value1;parameter2:value2;... 
            These values will be passed on and not optimized.
        mark_outlying_points <int>: See KFoldCV
    Returns:
        Analysis in the save_path folder
        Plots results in a predicted vs. measured square plot.
    Raises:
        ValueError if testing target data is None; CV must have
                testing target data
    """
    def __init__(self, 
        training_dataset=None,
        testing_dataset=None,
        model=None,
        save_path=None,
        xlabel="Measured",
        ylabel="Predicted",
        #param_1 and as many param_xxx as necessary are given through **kwargs
        additional_feature_methods=None,
        fix_random_for_testing=0,
        num_cvtests=5,
        mark_outlying_points='0,3',
        num_folds=None,
        percent_leave_out=None,
        processors=1,
        *args, **kwargs):
        """
        Additional class attributes to parent class:
            Set by keyword:
                self.additional_feature_methods
                self.fix_random_for_testing
                self.num_cvtests
                self.mark_outlying_points
                self.num_folds
                self.percent_leave_out
                self.processors
            Set in code:
                self.param_strings
                self.opt_dict
                self.opt_param_list
                self.nonopt_param_list
                self.flat_params
                self.flat_results
                self.pop_params
                self.pop_size
                self.pop_stats
                self.pop_rmses
                self.pop_upper_limit
                self.best_indivs
                ?self.random_state
        """
        if not(training_dataset == testing_dataset):
            raise ValueError("Only testing_dataset will be used. Use the same values for training_dataset and testing_dataset")
        SingleFit.__init__(self, 
            training_dataset=training_dataset, #only testing_dataset is used
            testing_dataset=testing_dataset,
            model=model, 
            save_path = save_path,
            xlabel=xlabel,
            ylabel=ylabel)
        self.fix_random_for_testing = int(fix_random_for_testing)
        if self.fix_random_for_testing == 1:
            self.random_state = np.random.RandomState(0)
        else:
            self.random_state = np.random.RandomState()
        if type(additional_feature_methods) is list:
            self.additional_feature_methods = list(additional_feature_methods)
        elif type(additional_feature_methods) is str:
            self.additional_feature_methods = additional_feature_methods.split(",")
        else:
            self.additional_feature_methods = additional_feature_methods
        self.num_cvtests = int(num_cvtests)
        self.mark_outlying_points = mark_outlying_points
        self.num_folds = num_folds
        self.percent_leave_out = percent_leave_out
        self.processors=int(processors)
        self.param_strings = dict()
        for argname in kwargs.keys():
            if 'param_' in argname:
                param_num = int(argname.split("_")[1].strip())
                self.param_strings[param_num] = kwargs[argname]
        # Sets later in code
        self.opt_dict=None
        self.opt_param_list=None
        self.nonopt_param_list=None
        self.flat_params=None
        self.pop_params=None
        self.pop_size=None
        self.pop_stats=None
        self.pop_rmses=None
        self.pop_upper_limit=1e6
        self.flat_results=None
        self.best_indivs=None
        return 

    @timeit
    def run(self):
        self.set_up()
        raise NotImplementedError("Stopping old setup.")
        self.evaluate_pop()
        self.get_best_indivs()
        self.print_best_params()
        self.flatten_results()
        self.plot()
        self.print_readme()
        return
    @timeit
    def set_up(self):
        SingleFit.set_up(self)
        self.set_up_opt_dict()
        logger.debug("opt dict: %s" % self.opt_dict)
        logger.debug("opt param list: %s" % self.opt_param_list)
        logger.debug("nonopt param list: %s" % self.nonopt_param_list)
        self.set_up_pop_params()
        logger.debug("Population: %s" % self.pop_params)
        logger.debug("Population size: %i" % len(self.pop_params))
        return
    


    @timeit
    def evaluate_pop(self):
        """make model and new testing dataset for each pop member
            and evaluate
        """
        self.pop_stats=dict()
        self.pop_rmses=np.zeros(self.pop_size)

        if self.processors == 1:
            for pidx in range(0, self.pop_size):
                print("Individual %i/%i (index %i)" % (pidx+1, self.pop_size, pidx))
                indiv_params = self.pop_params[pidx]
                [indiv_rmse, indiv_stats] = self.evaluate_indiv(indiv_params, pidx)
                self.pop_stats[pidx] = indiv_stats
                self.pop_rmses[pidx] = indiv_rmse
        else:
            from multiprocessing import Process, Manager
            manager = Manager()
            pop_stats_dict = manager.dict()
            pop_rmses_list = manager.list(range(self.pop_size))
            for pidx in range(0, self.pop_size):
                pop_rmses_list[pidx] = 0
            indiv_p_list=list()
            for pidx in range(0, self.pop_size):
                print("Individual %i/%i (index %i)" % (pidx+1, self.pop_size, pidx))
                indiv_params = self.pop_params[pidx]
                indiv_p = Process(target=self.evaluate_indiv_multiprocessing, args=(indiv_params, pidx, pop_stats_dict, pop_rmses_list))
                indiv_p_list.append(indiv_p)
                indiv_p.start()
            for indiv_p in indiv_p_list:
                indiv_p.join()
            self.pop_stats = pop_stats_dict
            self.pop_rmses = pop_rmses_list
        return

    def evaluate_indiv_multiprocessing(self, indiv_params, indiv_ct, pop_stats_dict, pop_rmses_list):
        [indiv_rmse, indiv_stats] = self.evaluate_indiv(indiv_params, indiv_ct)
        pop_stats_dict[indiv_ct] = indiv_stats
        pop_rmses_list[indiv_ct] = indiv_rmse
        print("Individual %i done (multiprocessing)" % indiv_ct)
        return

    def evaluate_indiv(self, indiv_params, indiv_ct):
        """Evaluate an individual
        """
        indiv_model = copy.deepcopy(self.model)
        indiv_model.set_params(**indiv_params['model'])
        indiv_dh = self.get_indiv_datahandler(indiv_params)
        #logging.debug(indiv_dh)
        indiv_path = os.path.join(self.save_path, "indiv_%i" % indiv_ct)
        if not(self.num_folds is None):
            mycv = KFoldCV(training_dataset= indiv_dh,
                    testing_dataset= indiv_dh,
                    model = indiv_model,
                    save_path = indiv_path,
                    xlabel = self.xlabel,
                    ylabel = self.ylabel,
                    mark_outlying_points = self.mark_outlying_points,
                    num_cvtests = self.num_cvtests,
                    fix_random_for_testing = self.fix_random_for_testing,
                    num_folds = self.num_folds)
            #mycv.run() #run separately instead
            mycv.set_up()
            mycv.fit()
            mycv.predict()
            mycv.print_readme()
            mycv_rmse = mycv.statistics['avg_fold_avg_rmses']
        elif not (self.percent_leave_out is None):
            mycv = LeaveOutPercentCV(training_dataset= indiv_dh,
                    testing_dataset= indiv_dh,
                    model = indiv_model,
                    save_path = indiv_path,
                    xlabel = self.xlabel,
                    ylabel = self.ylabel,
                    mark_outlying_points = self.mark_outlying_points,
                    num_cvtests = self.num_cvtests,
                    fix_random_for_testing = self.fix_random_for_testing,
                    percent_leave_out = self.percent_leave_out)
            #mycv.run() #run separately instead
            mycv.set_up()
            mycv.fit()
            mycv.predict()
            mycv.print_readme()
            mycv_rmse = mycv.statistics['avg_rmse']
        else:
            raise ValueError("Both self.num_folds and self.percent_leave_out are None. One or the other must be specified.")
        with open(os.path.join(indiv_path,"param_values"), 'w') as indiv_pfile:
            for loc in indiv_params.keys():
                for param in indiv_params[loc].keys():
                    val = indiv_params[loc][param]
                    indiv_pfile.write("%s, %s: %s\n" % (loc, param, val))
        return [mycv_rmse, mycv.statistics]

    def get_best_indivs(self):
        how_many = min(10, len(self.pop_rmses))
        largeval=1e10
        lowest = list()
        params = copy.deepcopy(self.pop_params)
        rmses = copy.deepcopy(self.pop_rmses)
        lct=0
        while lct < how_many:
            minidx = np.argmin(rmses)
            lowest.append((minidx, rmses[minidx], params[minidx]))
            rmses[minidx]=largeval
            lct = lct + 1
        self.readme_list.append("----Minimum RMSE params----\n")
        for lowitem in lowest:
            self.readme_list.append("%s: %3.3f, %s\n" % (lowitem[0],lowitem[1],lowitem[2]))
        self.readme_list.append("-----------------------\n")
        self.best_indivs = lowest
        return

    def print_best_params(self):
        best_params = self.best_indivs[0][2]
        with open(os.path.join(self.save_path,"OPTIMIZED_PARAMS"),'w') as pfile:
            for loc in best_params.keys():
                for param in best_params[loc].keys():
                    val = best_params[loc][param]
                    pfile.write("%s;%s;%s\n" % (loc, param, val))
        return

    def get_afm_updated_dataset(self, indiv_df, indiv_params):
        """Update dataframe with additional feature methods
        """
        for afm in indiv_params.keys():
            if afm == 'model': #model dealt with separately
                continue 
            afm_kwargs = dict(indiv_params[afm])
            (feature_name,feature_data)=cf_help.get_custom_feature_data(afm,
                        starting_dataframe = indiv_df,
                        addl_feature_method_kwargs = dict(afm_kwargs))
            fio = FeatureIO(indiv_df)
            indiv_df = fio.add_custom_features([afm], feature_data)
        return indiv_df

    def get_indiv_datahandler(self, indiv_params):
        indiv_dh = copy.deepcopy(self.testing_dataset)
        indiv_dataframe = self.get_afm_updated_dataset(indiv_dh.data, indiv_params)
        indiv_dh.data = indiv_dataframe
        for afm in indiv_params.keys():
            if afm == 'model':
                continue
            indiv_dh.input_features.append(afm)
        indiv_dh.set_up_data_from_features()
        return indiv_dh

    def flatten_params(self):
        flat_params=list()
        for location in self.opt_dict.keys():
            for param in self.opt_dict[location].keys():
                paramlist=list()
                for val in self.opt_dict[location][param]:
                    paramlist.append([location,param,val])
                flat_params.append(paramlist)
        logger.debug("Flattened:")
        for flat_item in flat_params:
            logger.debug(flat_item)
        self.flat_params = flat_params
        return

    def get_split_name(self, combined_name):
        """ model.param or package.class.param to
            (model, param) or (package.class, param)
        """
        name_split = combined_name.split(".")
        param_name = name_split.pop(-1) #get and remove
        location = str.join(".", name_split) #join back up
        return (location, param_name)

    def grow_param_dict(self, old_dict, add_combined_name):
        """Increase the parameter dictionary by having each entry
            branch into new entries
        """
        add_vals = self.opt_dict[add_combined_name]
        (location, param_name) = self.get_split_name(add_combined_name)
        if len(old_dict.keys()) == 0:
            new_dict = dict()
            for addct in range(0, len(add_vals)):
                newstr = "%i" % addct
                new_dict[newstr]=dict()
                if not location in new_dict[newstr].keys():
                    new_dict[newstr][location]=dict()
                new_dict[newstr][location][param_name] = add_vals[addct]
        else:
            new_dict = dict()
            for oldstr in old_dict.keys():
                for addct in range(0, len(add_vals)):
                    newstr = "%s_%i" % (oldstr, addct) 
                    new_dict[newstr] = copy.deepcopy(old_dict[oldstr])
                    if not location in new_dict[newstr].keys():
                        new_dict[newstr][location]=dict()
                    new_dict[newstr][location][param_name] = add_vals[addct]
        return new_dict
    
    def grow_param_dict_nonopt(self, old_dict, add_combined_name):
        """Add nonoptimized parameters (single value) to parameter
            dictionary.
        """
        add_value = self.opt_dict[add_combined_name]
        (location, param_name) = self.get_split_name(add_combined_name)
        if len(old_dict.keys()) == 0:
            raise ValueError("No optimized parameters in grid search? Run SingleFit or other tests instead.")
        new_dict = dict()
        for oldstr in old_dict.keys():
            newstr = oldstr
            new_dict[newstr] = copy.deepcopy(old_dict[oldstr])
            if not location in new_dict[newstr].keys():
                new_dict[newstr][location]=dict()
            new_dict[newstr][location][param_name] = add_value
        return new_dict

    def set_up_pop_params(self):
        self.pop_params=dict()
        for opt_param in self.opt_param_list:
            self.pop_params = self.grow_param_dict(self.pop_params, opt_param)
        for nonopt_param in self.nonopt_param_list:
            self.pop_params = self.grow_param_dict_nonopt(self.pop_params, nonopt_param)
        return

    def set_up_opt_dict(self):
        """Set up parameter value dictionary based on parameter strings, into
            self.opt_dict
            Also sets:
                self.opt_param_list (only those parameters which will be
                                    optimized)
                self.nonopt_param_list
                self.pop_size
        """
        self.opt_dict=dict()
        self.opt_param_list=list()
        self.nonopt_param_list=list()
        pop_size = None
        for paramct in self.param_strings.keys():
            paramstr = self.param_strings[paramct]
            logger.debug(paramstr)
            paramsplit = paramstr.strip().split(";")
            location = paramsplit[0].strip()
            paramname = paramsplit[1].strip()
            paramtype = paramsplit[2].strip().lower()
            if not(paramtype in ['int','float','bool','str']):
                raise ValueError("Parameter type %s must be one of int, float, bool, or str. Exiting." % paramtype)
            rangetype = paramsplit[3].strip().lower()
            if not(rangetype in ['discrete','continuous','continuous-log']):
                raise ValueError("Range type %s must be 'discrete' or 'continuous' or 'continuous-log'. Exiting." % rangetype) 
            if paramtype in ['bool', 'str']:
                if not(rangetype in ['discrete']):
                    raise ValueError("Range type %s must be discrete for parameter type of %s" % (rangetype, paramtype))
            gridinfo = paramsplit[4].strip()
            combined_name = "%s.%s" % (location, paramname)
            if combined_name in self.opt_dict.keys():
                raise KeyError("Parameter %s for optimization of %s appears to be listed twice. Exiting." % (paramname, location))
            gridsplit = gridinfo.split(":") #split colon-delimited
            gridsplit = np.array(gridsplit, paramtype)
            if rangetype == 'discrete':
                gridvals = gridsplit
            elif rangetype == 'continuous':
                gridvals = np.linspace(start=gridsplit[0],
                                        stop=gridsplit[1],
                                        num=gridsplit[2],
                                        endpoint=True,
                                        dtype=paramtype)
            elif rangetype == 'continuous-log':
                gridvals = np.logspace(start=gridsplit[0],
                                        stop=gridsplit[1],
                                        num=gridsplit[2],
                                        endpoint=True,
                                        dtype=paramtype)
            numvals = len(gridvals)
            if numvals < 1:
                raise ValueError("Parameter %s does not evaluate to having any values." % paramstr)
            elif numvals > 1: #optimization to be done
                self.opt_param_list.append(combined_name)
                self.opt_dict[combined_name] = gridvals
            elif numvals == 1: #
                self.nonopt_param_list.append(combined_name)
                self.opt_dict[combined_name] = gridvals[0]
            if pop_size is None:
                pop_size = numvals
            else:
                pop_size = pop_size * numvals
            if pop_size > self.pop_upper_limit:
                raise ValueError("Population size has reached the upper limit of %i. Exiting." % self.pop_upper_limit)
        self.pop_size = pop_size
        return

    @timeit
    def fit(self):
        self.cv_fit_and_predict()
        return

    @timeit
    def predict(self):
        #Predictions themselves are covered in self.fit()
        self.get_statistics()
        self.print_statistics()
        self.readme_list.append("----- Output data -----\n")
        self.print_best_worst_output_csv("best_and_worst")
        return

    @timeit
    def plot(self):
        self.readme_list.append("----- Plotting -----\n")
        cols=list() #repeated code; may want to reduce
        for fplist in self.flat_params:
            loc=fplist[0][0]
            param=fplist[0][1]
            cols.append("%s.%s" % (loc, param))
        for col in cols:
            self.plot_single_rmse(col)
        if len(cols) == 2:
            self.plot_2d_rmse_heatmap(cols)
        elif len(cols) == 3:
            self.plot_3d_rmse_heatmap(cols)
        return

    def is_log_param(self, col):
        """Check to see if flattened column was a log parameter
        """
        location=col.split(".")[0]
        param=col.split(".")[1]
        for init_param in [self.param_1,self.param_2,self.param_3,self.param_4]:
            if init_param is None:
                continue
            if location in init_param:
                if param in init_param:
                    if 'log' in init_param:
                        return True
        return False
    
    def plot_3d_rmse_heatmap(self, cols):
        #adjust for log params if necessary
        xcol = cols[0]
        ycol = cols[1]
        zcol = cols[2]
        xdata = self.flat_results[xcol]
        xlabel = xcol
        if self.is_log_param(xcol):
            xdata_raw = np.array(self.flat_results[xcol].values,'float')
            xdata = np.log10(xdata_raw)
            xlabel = "log10 %s" % xcol 
        ydata = self.flat_results[ycol]
        ylabel = ycol
        if self.is_log_param(ycol):
            ydata_raw = np.array(self.flat_results[ycol].values,'float')
            ydata = np.log10(ydata_raw)
            ylabel = "log10 %s" % ycol 
        zdata = self.flat_results[zcol]
        zlabel = zcol
        if self.is_log_param(zcol):
            zdata_raw = np.array(self.flat_results[zcol].values,'float')
            zdata = np.log10(zdata_raw)
            zlabel = "log10 %s" % zcol 
        kwargs = dict()
        kwargs['xlabel'] = xlabel
        kwargs['ylabel'] = ylabel
        kwargs['labellist'] = ['xy',zlabel,'RMSE']
        kwargs['xdatalist'] = [xdata, xdata, xdata]
        kwargs['ydatalist'] = [ydata, zdata, self.flat_results['rmse']]
        kwargs['xerrlist'] = [None, None, None]
        kwargs['yerrlist'] = [None, None, None]
        kwargs['notelist'] = list()
        kwargs['guideline'] = 0
        plotlabel="rmse_heatmap_3d"
        kwargs['plotlabel'] = plotlabel
        kwargs['save_path'] = self.save_path
        myph = PlotHelper(**kwargs)
        myph.plot_3d_rmse_heatmap()
        self.readme_list.append("Plot %s.png created\n" % plotlabel)
        return

    def plot_2d_rmse_heatmap(self, cols):
        #adjust for log params if necessary
        xcol = cols[0]
        ycol = cols[1]
        xdata = np.array(self.flat_results[xcol])
        xlabel = xcol
        if self.is_log_param(xcol):
            xdata_raw = np.array(self.flat_results[xcol].values,'float')
            xdata = np.log10(xdata_raw)
            xlabel = "log10 %s" % xcol 
        ydata = np.array(self.flat_results[ycol])
        ylabel = ycol
        if self.is_log_param(ycol):
            ydata_raw = np.array(self.flat_results[ycol].values,'float')
            ydata = np.log10(ydata_raw)
            ylabel = "log10 %s" % ycol 
        kwargs = dict()
        kwargs['xlabel'] = xlabel
        kwargs['ylabel'] = ylabel
        kwargs['labellist'] = ['xy','rmse']
        kwargs['xdatalist'] = [xdata, xdata]
        kwargs['ydatalist'] = [ydata, self.flat_results['rmse']]
        kwargs['xerrlist'] = [None, None]
        kwargs['yerrlist'] = [None, None]
        kwargs['notelist'] = list()
        kwargs['guideline'] = 0
        plotlabel="rmse_heatmap"
        kwargs['plotlabel'] = plotlabel
        kwargs['save_path'] = self.save_path
        myph = PlotHelper(**kwargs)
        myph.plot_2d_rmse_heatmap()
        self.readme_list.append("Plot %s.png created\n" % plotlabel)
        return

    def plot_single_rmse(self, col):
        #adjust for log params if necessary
        xdata = self.flat_results[col]
        xlabel = col
        if self.is_log_param(col):
            import numpy as np
            xdata_raw = np.array(self.flat_results[col].values,'float')
            xdata = np.log10(xdata_raw)
            xlabel = "log10 %s" % col 
        kwargs = dict()
        kwargs['xlabel'] = xlabel
        kwargs['ylabel'] = 'RMSE'
        kwargs['labellist'] = [xlabel]
        kwargs['xdatalist'] = [xdata]
        kwargs['ydatalist'] = [self.flat_results['rmse']]
        kwargs['xerrlist'] = list([None])
        kwargs['yerrlist'] = list([None])
        kwargs['notelist'] = list()
        kwargs['guideline'] = 0
        plotlabel="rmse_vs_%s" % col
        plotlabel=plotlabel.replace(".","_") #mask periods
        kwargs['plotlabel'] = plotlabel
        kwargs['save_path'] = self.save_path
        myph = PlotHelper(**kwargs)
        myph.multiple_overlay()
        self.readme_list.append("Plot %s.png created\n" % plotlabel)
        return

    def plot_pair(self):
        return

    def flatten_results(self):
        """Flatten results into a csv
        """
        cols=list()
        for fplist in self.flat_params:
            loc=fplist[0][0]
            param=fplist[0][1]
            cols.append("%s.%s" % (loc, param))
        cols.append('rmse')
        flat_results = pd.DataFrame(index=range(0, self.pop_size), columns=cols)
        for pct in range(0, self.pop_size):
            params = self.pop_params[pct]
            rmse = self.pop_rmses[pct]
            for loc in params.keys():
                for param in params[loc].keys():
                    colname = "%s.%s" % (loc, param)
                    val = params[loc][param]
                    flat_results.set_value(pct, colname, val)
            flat_results.set_value(pct, 'rmse', rmse)
        flat_results.to_csv(os.path.join(self.save_path, "results.csv"))
        self.flat_results = flat_results
        return

    def set_up_cv(self):
        if self.testing_dataset.target_data is None:
            raise ValueError("Testing target data cannot be none for cross validation.")
        indices = np.arange(0, len(self.testing_dataset.target_data))
        self.readme_list.append("----- CV setup -----\n")
        self.readme_list.append("%i CV tests,\n" % self.num_cvtests)
        self.readme_list.append("leaving out %i percent\n" % self.percent_leave_out)
        test_fraction = self.percent_leave_out / 100.0
        self.cvmodel = ShuffleSplit(n_splits = 1, 
                            test_size = test_fraction, 
                            random_state = None)
        for cvtest in range(0, self.num_cvtests):
            self.cvtest_dict[cvtest] = dict()
            for train, test in self.cvmodel.split(indices):
                fdict=dict()
                fdict['train_index'] = train
                fdict['test_index'] = test
                self.cvtest_dict[cvtest]= dict(fdict)
        return
    
    def cv_fit_and_predict(self):
        for cvtest in self.cvtest_dict.keys():
            prediction_array = np.zeros(len(self.testing_dataset.target_data))
            prediction_array[:] = np.nan
            fdict = self.cvtest_dict[cvtest]
            input_train=self.testing_dataset.input_data.iloc[fdict['train_index']]
            target_train = self.testing_dataset.target_data[fdict['train_index']]
            input_test=self.testing_dataset.input_data.iloc[fdict['test_index']]
            target_test = self.testing_dataset.target_data[fdict['test_index']]
            fit = self.model.fit(input_train, target_train)
            predict_test = self.model.predict(input_test)
            rmse = np.sqrt(mean_squared_error(predict_test, target_test))
            merr = np.mean(predict_test - target_test)
            prediction_array[fdict['test_index']] = predict_test
            self.cvtest_dict[cvtest]["rmse"] = rmse
            self.cvtest_dict[cvtest]["mean_error"] = merr
            self.cvtest_dict[cvtest]["prediction_array"] = prediction_array
        return

    def get_statistics(self):
        cvtest_rmses = list()
        cvtest_mean_errors = list()
        for cvtest in range(0, self.num_cvtests):
            cvtest_rmses.append(self.cvtest_dict[cvtest]["rmse"])
            cvtest_mean_errors.append(self.cvtest_dict[cvtest]["mean_error"])
        highest_rmse = max(cvtest_rmses)
        self.worst_test_index = cvtest_rmses.index(highest_rmse)
        lowest_rmse = min(cvtest_rmses)
        self.best_test_index = cvtest_rmses.index(lowest_rmse)
        self.statistics['avg_rmse'] = np.mean(cvtest_rmses)
        self.statistics['std_rmse'] = np.std(cvtest_rmses)
        self.statistics['avg_mean_error'] = np.mean(cvtest_mean_errors)
        self.statistics['std_mean_error'] = np.std(cvtest_mean_errors)
        self.statistics['rmse_best'] = lowest_rmse
        self.statistics['rmse_worst'] = highest_rmse
        return

    def print_best_worst_output_csv(self, label=""):
        """
        """
        olabel = "%s_test_data.csv" % label
        ocsvname = os.path.join(self.save_path, olabel)
        self.testing_dataset.add_feature("Best Prediction", 
                    self.cvtest_dict[self.best_test_index]['prediction_array'])
        self.testing_dataset.add_feature("Worst Prediction", 
                    self.cvtest_dict[self.worst_test_index]['prediction_array'])
        cols = self.testing_dataset.print_data(ocsvname, ["Best Prediction", "Worst Prediction"])
        self.readme_list.append("%s file created with columns:\n" % olabel)
        for col in cols:
            self.readme_list.append("    %s\n" % col)
        return


    def plot_best_worst_overlay(self, notelist=list()):
        kwargs2 = dict()
        kwargs2['xlabel'] = self.xlabel
        kwargs2['ylabel'] = self.ylabel
        kwargs2['labellist'] = ["Best test","Worst test"]
        kwargs2['xdatalist'] = list([self.testing_dataset.target_data, 
                            self.testing_dataset.target_data])
        kwargs2['ydatalist'] = list(
                [self.cvtest_dict[self.best_test_index]['prediction_array'],
                self.cvtest_dict[self.worst_test_index]['prediction_array']])
        kwargs2['xerrlist'] = list([None,None])
        kwargs2['yerrlist'] = list([None,None])
        kwargs2['notelist'] = list(notelist)
        kwargs2['guideline'] = 1
        kwargs2['plotlabel'] = "best_worst_overlay"
        kwargs2['save_path'] = self.save_path
        if not (self.mark_outlying_points is None):
            kwargs2['marklargest'] = self.mark_outlying_points
            if self.testing_dataset.labeling_features is None:
                raise ValueError("Must specify some labeling features if you want to mark the largest outlying points")
            labels = self.testing_dataset.data[self.testing_dataset.labeling_features[0]]
            kwargs2['mlabellist'] = list([labels,labels])
        myph = PlotHelper(**kwargs2)
        myph.multiple_overlay()
        self.readme_list.append("Plot best_worst_overlay.png created,\n")
        self.readme_list.append("    showing the best and worst of %i tests.\n" % self.num_cvtests)
        return
