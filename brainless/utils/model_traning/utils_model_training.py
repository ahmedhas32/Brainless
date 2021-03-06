import datetime
import gc
import os
import random
import warnings
from collections import Iterable
from copy import deepcopy

import numpy as np
import pandas as pd
from scipy import sparse as scipy_sparse
from sklearn import __version__ as sklearn_version
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.model_selection import train_test_split

from brainless.utils.models import utils_models
from brainless.utils.models.utils_models import get_name_from_model

try:
    from keras import Sequential
    from keras.layers import Dense
    from keras.callbacks import EarlyStopping, ModelCheckpoint, TerminateOnNaN
    from keras.models import load_model as keras_load_model
    from keras.wrappers.scikit_learn import KerasRegressor, KerasClassifier

    keras_installed = True
except ImportError:
    keras_installed = False


# This is the Air Traffic Controller (ATC) that is a wrapper around sklearn estimators.

# In short, it wraps all the methods the pipeline will look for (fit, score, predict,
# predict_proba, etc.) However, it also gives us the ability to optimize this stage in
# conjunction with the rest of the pipeline. It also gives us more granular control over things
# like turning the input for GradientBoosting into dense matrices, or appending a set of dummy
# 1's to the end of sparse matrices getting predictions from XGBoost.


class FinalModelATC(BaseEstimator, TransformerMixin):

    def __init__(self,
                 model,
                 model_name=None,
                 ml_for_analytics=False,
                 type_of_estimator='classifier',
                 name=None,
                 _scorer=None,
                 training_features=None,
                 column_descriptions=None,
                 feature_learning=False,
                 uncertainty_model=None,
                 uc_results=None,
                 training_prediction_intervals=False,
                 min_step_improvement=0.0001,
                 interval_predictors=None,
                 keep_cat_features=False,
                 is_hp_search=None,
                 X_test=None,
                 y_test=None):

        self.model = model
        self.model_name = model_name
        self.ml_for_analytics = ml_for_analytics
        self.type_of_estimator = type_of_estimator
        self.name = name
        self.training_features = training_features
        self.column_descriptions = column_descriptions
        self.feature_learning = feature_learning
        self.uncertainty_model = uncertainty_model
        self.uc_results = uc_results
        self.training_prediction_intervals = training_prediction_intervals
        self.min_step_improvement = min_step_improvement
        self.interval_predictors = interval_predictors
        self.is_hp_search = is_hp_search
        self.keep_cat_features = keep_cat_features
        self.X_test = X_test
        self.y_test = y_test
        self.memory_optimized = False
        self._scorer = _scorer

    def get(self, prop_name, default=None):
        try:
            return getattr(self, prop_name)
        except AttributeError:
            return default

    # TODO: Simplify
    def fit(self, X, y):

        self.model_name = get_name_from_model(self.model)

        X_fit = X

        if self.model_name[:12] == 'DeepLearning' or self.model_name in [
            'BayesianRidge', 'LassoLars', 'OrthogonalMatchingPursuit', 'ARDRegression',
            'Perceptron', 'PassiveAggressiveClassifier', 'SGDClassifier', 'RidgeClassifier',
            'LogisticRegression', 'XGBClassifier', 'XGBRegressor'
        ]:

            if self.model_name[:3] == 'XGB' and scipy_sparse.issparse(X):
                ones = [[1] for _ in range(X.shape[0])]
                # Trying to force XGBoost to play nice with sparse matrices
                X_fit = scipy_sparse.hstack((X, ones))

            elif scipy_sparse.issparse(X_fit):
                X_fit = X_fit.todense()

            if self.model_name[:12] == 'DeepLearning':
                if keras_installed is False:
                    # Suppress some level of logs
                    os.environ['TF_CPP_MIN_VLOG_LEVEL'] = '3'
                    os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

                # For Keras, we need to tell it how many input nodes to expect, which is our
                # num_cols
                num_cols = X_fit.shape[1]

                model_params = self.model.get_params()
                del model_params['build_fn']
                try:
                    del model_params['feature_learning']
                except:
                    # TODO: Fix bare Except
                    pass
                try:
                    del model_params['num_cols']
                except:
                    # TODO: Fix bare Except
                    pass

                if self.type_of_estimator == 'regressor':
                    self.model = KerasRegressor(
                        build_fn=utils_models.make_deep_learning_model,
                        num_cols=num_cols,
                        feature_learning=self.feature_learning,
                        **model_params)
                elif self.type_of_estimator == 'classifier':
                    self.model = KerasClassifier(
                        build_fn=utils_models.make_deep_learning_classifier,
                        num_cols=num_cols,
                        feature_learning=self.feature_learning,
                        **model_params)

        if self.model_name[:12] == 'DeepLearning':
            try:

                if self.is_hp_search is True:
                    patience = 5
                    verbose = 0
                else:
                    patience = 25
                    verbose = 2

                X_fit, y, X_test, y_test = self.get_X_test(X_fit, y)
                if isinstance(X_test, pd.DataFrame):
                    X_test = X_test.values
                else:
                    # TODO: Try to improve flow control
                    try:
                        X_test = X_test.toarray()
                    except AttributeError:
                        pass

                if not self.is_hp_search:
                    print('\nWe will stop training early if we have not seen an improvement in '
                          'validation accuracy in {} epochs '.format(patience))
                    print(
                        'To measure validation accuracy, we will split off a random 10 percent of '
                        'your training data set ')

                early_stopping = EarlyStopping(
                    monitor='val_loss', patience=patience, verbose=verbose)
                terminate_on_nan = TerminateOnNaN()

                now_time = datetime.datetime.now()
                time_string = str(now_time.year) + '_' + str(now_time.month) + '_' + str(
                    now_time.day) + '_' + str(now_time.hour) + '_' + str(now_time.minute)

                temp_file_name = 'tmp_dl_model_checkpoint_' + time_string + str(
                    random.random()) + '.h5'
                model_checkpoint = ModelCheckpoint(
                    temp_file_name, monitor='val_loss', save_best_only=True, mode='min', period=1)

                callbacks = [early_stopping, terminate_on_nan]
                if not self.is_hp_search:
                    callbacks.append(model_checkpoint)

                self.model.fit(
                    X_fit,
                    y,
                    callbacks=callbacks,
                    validation_data=(X_test, y_test),
                    verbose=verbose)

                # TODO: give some kind of logging on how the model did here! best epoch,
                #  best accuracy, etc.

                if self.is_hp_search is False:
                    self.model = keras_load_model(temp_file_name)

                    # TODO: Try to improve flow control
                try:
                    os.remove(temp_file_name)
                except OSError:
                    pass
            except KeyboardInterrupt:
                print('Stopping training at this point because we heard a KeyboardInterrupt')
                print('If the deep learning model is functional at this point, we will output the '
                      'model in its latest form ')
                print('Note that this feature is an unofficial beta-release feature that is known '
                      'to fail on occasion ')

                if self.is_hp_search is False:
                    # TODO: Make sure that temp_file_name is initialized
                    self.model = keras_load_model(temp_file_name)
                    # TODO: Try to improve flow control
                try:
                    os.remove(temp_file_name)
                except OSError:
                    pass

        elif self.model_name[:4] == 'LGBM':

            if scipy_sparse.issparse(X_fit):
                X_fit = X_fit.toarray()

            verbose = True
            if self.is_hp_search is True:
                verbose = False

            train_dynamic_n_estimators = False
            if self.model.get_params()['n_estimators'] == 2000:
                train_dynamic_n_estimators = True

                X_fit, y, X_test, y_test = self.get_X_test(X_fit, y)

                # TODO: Try to improve flow control
                try:
                    X_test = X_test.toarray()
                except AttributeError:
                    pass

                if self.X_test is not None:
                    eval_name = 'X_test_the_user_passed_in'
                else:
                    eval_name = 'random_holdout_set_from_training_data'

                if self.type_of_estimator == 'regressor':
                    if self.training_prediction_intervals is True:
                        eval_metric = 'quantile'
                    else:
                        eval_metric = 'rmse'
                elif self.type_of_estimator == 'classifier':
                    if len(set(y_test)) > 2:
                        eval_metric = 'multi_logloss'
                    else:
                        eval_metric = 'binary_logloss'

            cat_feature_indices = self.get_categorical_feature_indices()
            if self.memory_optimized is True:
                X_fit.to_csv('_lgbm_dataset.csv')
                del X_fit

            if cat_feature_indices is None:
                if train_dynamic_n_estimators:
                    self.model.fit(
                        X_fit,
                        y,
                        # TODO: Make sure that these are initialized
                        eval_set=[(X_test, y_test)],
                        early_stopping_rounds=100,
                        # TODO: Make sure that eval_metric and eval_names are initialized
                        eval_metric=eval_metric,
                        eval_names=[eval_name],
                        verbose=verbose)
                else:
                    self.model.fit(X_fit, y, verbose=verbose)
            else:
                if train_dynamic_n_estimators:
                    self.model.fit(
                        X_fit,
                        y,
                        # TODO: Similar to above; make sure that all of these are initialized
                        eval_set=[(X_test, y_test)],
                        early_stopping_rounds=100,
                        eval_metric=eval_metric,
                        eval_names=[eval_name],
                        categorical_feature=cat_feature_indices,
                        verbose=verbose)
                else:
                    self.model.fit(
                        X_fit, y, categorical_feature=cat_feature_indices, verbose=verbose)

        elif self.model_name[:8] == 'CatBoost':
            if isinstance(X_fit, pd.DataFrame):
                X_fit = X_fit.values
            else:
                X_fit = X_fit.toarray()

            if self.type_of_estimator == 'classifier' and len(pd.Series(y).unique()) > 2:
                # TODO: we might have to modify the format of the y values, converting them all
                #  to ints, then back again (sklearn has a useful inverse_transform on some
                #  preprocessing classes)
                self.model.set_params(loss_function='MultiClass')

            cat_feature_indices = self.get_categorical_feature_indices()

            self.model.fit(X_fit, y, cat_features=cat_feature_indices)

        elif self.model_name[:16] == 'GradientBoosting':
            if not sklearn_version > '0.18.1':
                if isinstance(X_fit, pd.DataFrame):
                    X_fit = X_fit.values
                else:
                    X_fit = X_fit.toarray()

            patience = 20
            best_val_loss = -10000000000
            num_worse_rounds = 0
            best_model = deepcopy(self.model)
            X_fit, y, X_test, y_test = self.get_X_test(X_fit, y)

            # Add a variable number of trees each time, depending how far into the process we are
            if os.environ.get('is_test_suite', False) == 'True':
                num_iters = list(range(1, 50, 1)) + list(range(50, 100, 2)) + list(
                    range(100, 250, 3))
            else:
                num_iters = list(range(1, 50, 1)) + list(range(50, 100, 2)) + list(
                    range(100, 250, 3)) + list(range(250, 500, 5)) + list(range(
                    500, 1000, 10)) + list(range(1000, 2000, 20)) + list(
                    range(2000, 10000, 100))
            # TODO: get n_estimators from the model itself, and reduce this list to only those
            #  values that come under the value from the model

            try:
                for num_iter in num_iters:
                    warm_start = True
                    if num_iter == 1:
                        warm_start = False

                    self.model.set_params(n_estimators=num_iter, warm_start=warm_start)
                    self.model.fit(X_fit, y)

                    if self.training_prediction_intervals is True:
                        val_loss = self.model.score(X_test, y_test)
                    else:
                        try:
                            val_loss = self._scorer.score(self, X_test, y_test)
                        except Exception:
                            # TODO: Fix bare Except
                            val_loss = self.model.score(X_test, y_test)

                    if val_loss - self.min_step_improvement > best_val_loss:
                        best_val_loss = val_loss
                        num_worse_rounds = 0
                        best_model = deepcopy(self.model)
                    else:
                        num_worse_rounds += 1
                    print('[' + str(num_iter) +
                          '] random_holdout_set_from_training_data\'s score is: ' +
                          str(round(val_loss, 3)))
                    if num_worse_rounds >= patience:
                        break
            except KeyboardInterrupt:
                print('Heard KeyboardInterrupt. Stopping training, and using the best '
                      'GradientBoosting model with a checkpoint')

            self.model = best_model
            print('The number of estimators that were the best for this training dataset: ' +
                  str(self.model.get_params()['n_estimators']))
            print('The best score on the holdout set: ' + str(best_val_loss))

        else:
            self.model.fit(X_fit, y)

        if self.X_test is not None:
            del self.X_test
            del self.y_test
        gc.collect()
        return self

    @staticmethod
    def remove_categorical_values(features):
        clean_features = set([])
        for feature in features:
            if '=' not in feature:
                clean_features.add(feature)
            else:
                clean_features.add(feature[:feature.index('=')])

        return clean_features

    # TODO: Simplify
    def verify_features(self, X, raw_features_only=False):

        if self.column_descriptions is None:
            print('This feature is not enabled by default. Depending on the shape of the training '
                  'data, it can add hundreds of KB to the saved file size. ')
            print('Please pass in `ml_predictor.train(data, verify_features=True)` when training a '
                  'model, and we will enable this function, at the cost of a potentially larger '
                  'file size. ')
            warnings.warn(
                'Please pass verify_features=True when invoking .train() on the ml_predictor '
                'instance. ')
            return None

        print('\n\nNow verifying consistency between training features and prediction features')
        if isinstance(X, dict):
            prediction_features = set(X.keys())
        elif isinstance(X, pd.DataFrame):
            prediction_features = set(X.columns)

        # If the user passed in categorical features, we will effectively one-hot-encode them
        # ourselves here.Note that this assumes we're using the "=" as the separator in
        # DictVectorizer/DataFrameVectorizer.
        date_col_names = []
        categorical_col_names = []
        for key, value in self.column_descriptions.items():
            if value == 'categorical' and 'day_part' not in key:
                try:
                    # This covers the case that the user passes in a value in column_descriptions
                    # that is not present in their prediction data
                    column_vals = X[key].unique()
                    for val in column_vals:
                        # TODO: Make sure that prediction_features is initialized
                        prediction_features.add(key + '=' + str(val))

                    categorical_col_names.append(key)
                except:
                    # TODO: Fix bare Except
                    print('\nFound a column in your column_descriptions that is not present '
                          'in your prediction data: ')
                    print(key)

            elif 'day_part' in key:
                # We have found a date column. Make sure this date column is in our prediction
                # data. It is outside the scope of this function to make sure that the same date
                # parts are available in both our training and testing data
                raw_date_col_name = key[:key.index('day_part') - 1]
                date_col_names.append(raw_date_col_name)

            elif value == 'output':
                # TODO: Try to improve flow control
                try:
                    prediction_features.remove(key)
                except KeyError:
                    pass

        # Now that we've added in all the one-hot-encoded categorical columns (name=val1,
        # name=val2), remove the base name from our prediction data
        prediction_features = prediction_features - set(categorical_col_names)

        # Get only the unique raw_date_col_names
        date_col_names = set(date_col_names)

        training_features = set(self.training_features)

        # Remove all of the transformed date column feature names from our training data
        features_to_remove = []
        for feature in training_features:
            for raw_date_col_name in date_col_names:
                if raw_date_col_name in feature:
                    features_to_remove.append(feature)
        training_features = training_features - set(features_to_remove)

        # Make sure the raw_date_col_name is in our training data after we have removed all the
        # transformed feature names
        training_features = training_features | date_col_names

        # MVP means ignoring text features
        print_nlp_warning = False
        nlp_example = None
        for feature in training_features:
            if 'nlp_' in feature:
                print_nlp_warning = True
                nlp_example = feature
                training_features.remove(feature)

        if print_nlp_warning is True:
            print('\n\nWe found an NLP column in the training data')
            print('verify_features() currently does not support checking all of the values within '
                  'an NLP column, so if the text of your NLP column has dramatically changed, '
                  'you will have to check that yourself. ')
            print('Here is one example of an NLP feature in the training data:')
            print(nlp_example)

        training_not_prediction = training_features - prediction_features

        if raw_features_only is True:
            training_not_prediction = self.remove_categorical_values(training_not_prediction)

        if len(training_not_prediction) > 0:

            print('\n\nHere are the features this model was trained on that were not present in '
                  'this prediction data: ')
            print(sorted(list(training_not_prediction)))
        else:
            print(
                'All of the features this model was trained on are included in the prediction data')

        prediction_not_training = prediction_features - training_features
        if raw_features_only is True:
            prediction_not_training = self.remove_categorical_values(prediction_not_training)

        if len(prediction_not_training) > 0:

            # Separate out those values we were told to ignore by column_descriptions
            ignored_features = []
            for feature in prediction_not_training:
                if self.column_descriptions.get(feature, 'False') == 'ignore':
                    ignored_features.append(feature)
            prediction_not_training = prediction_not_training - set(ignored_features)

            print('\n\nHere are the features available in the prediction data '
                  'that were not part of the training data: ')
            print(sorted(list(prediction_not_training)))

            if len(ignored_features) > 0:
                print('\n\nAdditionally, we found features in the prediction '
                      'data that we were told to ignore in the training data ')
                print(sorted(list(ignored_features)))

        else:
            print('All of the features in the prediction data were in this model\'s training data')

        print('\n\n')
        return {
            'training_not_prediction': training_not_prediction,
            'prediction_not_training': prediction_not_training
        }

    def score(self, X, y):
        # At the time of writing this, GradientBoosting does not support sparse matrices for
        # predictions
        if (self.model_name[:16] == 'GradientBoosting' or self.model_name in [
            'BayesianRidge', 'LassoLars', 'OrthogonalMatchingPursuit', 'ARDRegression'
        ]) and scipy_sparse.issparse(X):
            X = X.todense()

        if self._scorer is not None:
            return self._scorer.score(self, X, y)

        else:
            return self.model.score(X, y)

    # TODO: Simplify
    def predict_proba(self, X):

        if self.model_name[:3] == 'XGB':
            ones = [[1] for _ in range(X.shape[0])]
            if scipy_sparse.issparse(X):
                # Trying to force XGBoost to play nice with sparse matrices
                X = scipy_sparse.hstack((X, ones))
            else:
                X = np.column_stack([X, ones])

        if (self.model_name[:16] == 'GradientBoosting' or self.model_name[:12] == 'DeepLearning'
                or self.model_name in [
                    'BayesianRidge', 'LassoLars', 'OrthogonalMatchingPursuit', 'ARDRegression'
                ]):
            if scipy_sparse.issparse(X):
                X = X.todense()
            elif isinstance(X, pd.DataFrame):
                X = X.values
        elif self.model_name[:8] == 'CatBoost' or self.model_name[:4] == 'LGBM':
            if scipy_sparse.issparse(X):
                X = X.toarray()
            elif isinstance(X, pd.DataFrame):
                X = X.values

        try:
            if self.model_name[:4] == 'LGBM':
                try:
                    best_iteration = self.model.best_iteration
                except AttributeError:
                    best_iteration = self.model.best_iteration_
                predictions = self.model.predict_proba(X, num_iteration=best_iteration)
            else:
                predictions = self.model.predict_proba(X)

        except AttributeError:
            try:
                predictions = self.model.predict(X)
            except TypeError:
                if scipy_sparse.issparse(X):
                    X = X.todense()
                predictions = self.model.predict(X)

        except TypeError:
            if scipy_sparse.issparse(X):
                X = X.todense()
            predictions = self.model.predict_proba(X)

        # If this model does not have predict_proba, and we have fallen back on predict,
        # we want to make sure we give results back in the same format the user would expect for
        # predict_proba, namely each prediction is a list of predicted probabilities for each
        # class.

        # Note that this DOES NOT WORK for multi-label problems, or problems that are not reduced
        # to 0,1

        # If this is not an iterable (ignoring strings, which might be iterable), then we will
        # want to turn our predictions into tupled predictions
        if not (hasattr(predictions[0], '__iter__') and not isinstance(predictions[0], str)):
            tupled_predictions = []
            for prediction in predictions:
                if prediction == 1:
                    tupled_predictions.append([0, 1])
                else:
                    tupled_predictions.append([1, 0])
            predictions = tupled_predictions

        # This handles an annoying edge case with libraries like Keras that, for a binary
        # classification problem, with return a single predicted probability in a list,
        # rather than the probability of both classes in a list
        if len(predictions[0]) == 1:
            tupled_predictions = []
            for prediction in predictions:
                tupled_predictions.append([1 - prediction[0], prediction[0]])
            predictions = tupled_predictions

        if X.shape[0] == 1:
            return predictions[0]
        else:
            return predictions

    # TODO: Simplify
    def predict(self, X):

        if self.model_name[:3] == 'XGB':
            ones = [[1] for _ in range(X.shape[0])]
            if scipy_sparse.issparse(X):
                # Trying to force XGBoost to play nice with sparse matrices
                X = scipy_sparse.hstack((X, ones))
            else:
                X = np.column_stack([X, ones])

        X_predict = X

        if (self.model_name[:16] == 'GradientBoosting' or self.model_name[:12] == 'DeepLearning'
                or self.model_name in [
                    'BayesianRidge', 'LassoLars', 'OrthogonalMatchingPursuit', 'ARDRegression'
                ]):
            if scipy_sparse.issparse(X):
                X_predict = X.todense()
            elif isinstance(X, pd.DataFrame):
                X_predict = X.values
        elif self.model_name[:8] == 'CatBoost':
            if scipy_sparse.issparse(X):
                X_predict = X.toarray()
            elif isinstance(X, pd.DataFrame):
                X_predict = X.values
        else:
            X_predict = X

        if self.model_name[:4] == 'LGBM':
            try:
                best_iteration = self.model.best_iteration_
            except AttributeError:
                best_iteration = self.model.best_iteration
            if best_iteration is None:
                best_iteration = 0
            predictions = self.model.predict(X, num_iteration=best_iteration)
        else:
            predictions = self.model.predict(X_predict)
        # Handle cases of getting a prediction for a single item. It makes a cleaner interface
        # just to get just the single prediction back, rather than a list with the prediction
        # hidden inside.

        if isinstance(predictions, np.ndarray):
            predictions = predictions.tolist()
            if isinstance(predictions, float) or isinstance(predictions, int) or isinstance(
                    predictions, str):
                return predictions

        if isinstance(predictions[0], list) and len(predictions[0]) == 1:
            predictions = [row[0] for row in predictions]

        if len(predictions) == 1:
            return predictions[0]
        else:
            return predictions

    # TODO: Simplify
    def predict_intervals(self, X, return_type=None):

        if self.interval_predictors is None:
            print('!' * 64)
            print('This model was not trained to predict intervals')
            print(
                'Please follow the documentation to tell this model at training time to learn how '
                'to predict intervals ')
            print('!' * 64)
            raise ValueError('This model was not trained to predict intervals')

        base_prediction = self.predict(X)

        result = {'prediction': base_prediction}
        for tup in self.interval_predictors:
            predictor_name = tup[0]
            predictor = tup[1]
            result[predictor_name] = predictor.predict(X)

        if scipy_sparse.issparse(X):
            len_input = X.shape[0]
        else:
            len_input = len(X)

        if (len_input == 1 and return_type is None) or return_type == 'dict':
            return result

        elif (len_input > 1
              and return_type is None) or return_type == 'df' or return_type == 'dataframe':
            return pd.DataFrame(result)

        elif return_type == 'list':
            if len_input == 1:
                list_result = [base_prediction]
                for tup in self.interval_predictors:
                    list_result.append(result[tup[0]])
            else:
                list_result = []
                for idx in range(len_input):
                    row_result = [base_prediction[idx]]
                    for tup in self.interval_predictors:
                        row_result.append(result[tup[0]][idx])
                    list_result.append(row_result)

            return list_result

        else:
            print('Please pass in a return_type value of one of the '
                  'following: ["dict", "dataframe", "df", "list"] ')
            raise (ValueError('Please pass in a return_type value of one of the '
                              'following: ["dict", "dataframe", "df", "list"] '))

    # transform is initially designed to be used with feature_learning
    def transform(self, X):
        predicted_features = self.predict(X)
        predicted_features = list(predicted_features)

        X = scipy_sparse.hstack([X, predicted_features], format='csr')
        return X

    # Allows the user to get the fully transformed data
    @staticmethod
    def transform_only(X):
        return X

    # TODO: Simplify
    def predict_uncertainty(self, X):
        if self.uncertainty_model is None:
            print('!' * 64)
            print('This model was not trained to predict uncertainties')
            print(
                'Please follow the documentation to tell this model at training time to learn how '
                'to predict uncertainties ')
            print('!' * 64)
            raise ValueError('This model was not trained to predict uncertainties')

        base_predictions = self.predict(X)

        if isinstance(base_predictions, Iterable):
            base_predictions_col = [[val] for val in base_predictions]
            base_predictions_col = np.array(base_predictions_col)
        else:
            base_predictions_col = [base_predictions]

        X_combined = scipy_sparse.hstack([X, base_predictions_col], format='csr')

        uncertainty_predictions = self.uncertainty_model.predict_proba(X_combined)

        results = {
            'base_prediction': base_predictions,
            'uncertainty_prediction': uncertainty_predictions
        }

        if isinstance(base_predictions, Iterable):

            results['uncertainty_prediction'] = [
                row[1] for row in results['uncertainty_prediction']
            ]

            results = pd.DataFrame.from_dict(results, orient='columns')

            if self.uc_results is not None:
                calibration_results = {}
                # grab the relevant properties from our uc_results, and make them each their own
                # list in calibration_results
                for key, value in self.uc_results[1].items():
                    calibration_results[key] = []

                for proba in results['uncertainty_prediction']:
                    max_bucket_proba = 0
                    bucket_num = 1
                    while proba > max_bucket_proba:
                        calibration_result = self.uc_results[bucket_num]
                        max_bucket_proba = self.uc_results[bucket_num]['max_proba']
                        bucket_num += 1

                    # TODO: Make sure that calibration_result is initialized
                    for key, value in calibration_result.items():
                        calibration_results[key].append(value)
                # TODO: grab the uncertainty_calibration data for DataFrames
                df_calibration_results = pd.DataFrame.from_dict(
                    calibration_results, orient='columns')
                del df_calibration_results['max_proba']

                results = pd.concat([results, df_calibration_results], axis=1)

        # else:
        #     if self.uc_results is not None:
        #         # TODO: grab the uncertainty_calibration data for dictionaries
        #         for bucket_name, bucket_result in self.uc_results.items():
        #             # Where is this supposed to come from?
        #             if proba > bucket_result['max_proba']:
        #                 break
        #             results.update(bucket_result)
        #             del results['max_proba']

        return results

    def score_uncertainty(self, X, y):
        return self.uncertainty_model.score(X, y, verbose=False)

    def get_categorical_feature_indices(self):
        cat_feature_indices = None
        if self.keep_cat_features is True:
            cat_feature_names = [
                k for k, v in self.column_descriptions.items() if v == 'categorical'
            ]
            cat_feature_indices = [
                self.training_features.index(cat_name) for cat_name in cat_feature_names
            ]

        return cat_feature_indices

    def get_X_test(self, X_fit, y):

        if self.X_test is not None:
            return X_fit, y, self.X_test, self.y_test
        else:
            X_fit, X_test, y, y_test = train_test_split(X_fit, y, test_size=0.15)
            return X_fit, y, X_test, y_test
