# auto_ml
> Get a trained and optimized machine learning predictor at the push of a button (and, admittedly, an extended coffee break while your computer does the heavy lifting and you get to claim "compiling" https://xkcd.com/303/). 


# WARNING: PERSON WORKING! 
This project is under active development. If you want to help, please check out the issues! 'Til it's done, you stand a better chance resurrecting the Wooly Mammoth than getting this package to behave like a properly trained adult. 

## Getting Started

1. `pip install auto_ml`
1. `from auto_ml import Predictor`
1. `ml_predictor = Predictor(type_of_algo='classifier')` can pass in `type_of_algo='regressor'` as well. 
1. `ml_predictor.train(my_formatted_but_otherwise_raw_training_data)`
1. `ml_predictor.predict(new_data)`

That's it!

## Formatting the data

The only tricky part you have to do is get your training data into the format specified. 

### Training data format
1. Must be a list (or other iterable) filled with python dictionaries.
1. The first dictionary in the list is essentially the header row. Here you've gotta specify some basic information about each "column" of data in the other dictionaries. This object should essentially have the same attributes as the following objects, except the values stored in each attribute will tell us information about that "column" of data. 
1. The non-header-row objects can be "sparse". That is, they don't have to have all the properties. So if you are missing data for a certain row, or have a property that only applies to certain rows, you can include it or not at your discretion. 

#### Header row information

1. `attribute_name: 'output'` The first object in your training data must specify one of your attributes as the output column that we're interested in training on. This is what the `auto_ml` predictor will try to predict. 
1. `attribute_name: 'categorical'` All attribute names that hold a string in any of the rows after the header row will be encoded as categorical data. If, however, you have any numerical columns that you want encoded as categorical data, you can specify that here. 
1. `attribute_name: 'nlp'` If any of your data is a text field that you'd like to run some Natural Language Processing on, specify that in the header row. Data stored in this attribute will be encoded using TF-IDF, along with some other feature engineering (count of some aggregations like total capital letters, puncutation characters, smiley faces, etc., as well as a sentiment prediction of that text). 


### Future API features that I definitely haven't built out yet
1. `grid_search` aka, `optimize_the_foobar_out_of_this_predictor`. Sit down for a long coffee break. Better yet, go make some cold brew. Come back when the cold brew's ready. As amped as you are on all that caffeine is as amped as this highly optimized algo will be. They'll also both take about the same amount of time to prepare. Both are best done overnight. 
1. Support for multiple nlp columns. 
1. `print_analytics_output` For the curious out there, sometimes we want to know what features are important. This option will let you figure that out. 

### Future internal features that you'll never see but will make this much better
1. Mostly, all kinds of stats-y feature engineering
  - RobustScaler
  - Handling correlated features
  - etc. 
  - These will be mostly used by GridSearchCV, and are probably not things that you'll get to specify unless you dive into the internals of the project. 
1. Feature selection
1. The ability to pass in a param_grid of your own to run during GridSearchCV that will override any of the properties we would use ourselves. Properties that are not valid will be logged to the console and summarily ignored. Yeah, it'll be ugly. That's what an MVP is for. Besides, you can handle it if you're diving this deep into the project. 
1. Ensembling of results. Honestly, probably not all that practical, as it will likely increase the computation time for making each prediction rather dramatically. Worth mentioning in case some other contributor wants to add it in, as it's likely highly useful for competitions. But, not super great for production environments, so I'll probably ignore it until a future where I get very bored. 

Just for kicks, here's how we'd implement ensembling:
Create our own custom transformer class.
This class will have a bunch of weak classifiers (non-tuned perceptrion, LinearRegression, etc.). 
This custom transformer class will then use each of these weak predictors in a FeatureUnion to get predictions on each row, and append it to that row's features. 
Then, we'll just continue on our merry way to the standard big predictor, using each of these weak predictions as features. It probably wouldn't increase the complexity too much, since we're using FeatureUnion to compute predictions in parallel...
Heavily caveat all this with how ensembling tends to overfit, so we'd probably have to build in significantly more complexity to evaluate all this on a holdout set of data. 
Just thoughts for a future future scenario in which I've already conquered all my other ML ambitions and found myself with bored time on my hands again...